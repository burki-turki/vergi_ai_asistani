# ============================================================
# VERGİ AI - LEGAL RESEARCH ENGINE V1
#
# AMAÇ
# ----
#
# Canonical issues.json (Row 9) + canonical facts + canonical
# timeline + (varsa) canonical deadline analysis üzerinden
# Legal Research Policy V1'i (deterministik Legal Knowledge
# Engine sorgulaması) çalıştırmak ve sonucu:
#
#     data/cases/<case_id>/research/
#     legal_research_<case_id>_v1.json.pending
#
# olarak üretmek.
#
#
# MİMARİ
# ------
#
# canonical issues + facts + timeline + deadline
#        ↓
# Legal Research Policy V1 (provision_repository +
#                            provision_version_policy +
#                            provision_policy)
#        ↓
# Legal Research Validator V1
#        ↓
# *.json.pending
#        ↓
# human approval
#        ↓
# canonical research.json
#
#
# KRİTİK GÜVENLİK
# ----------------
#
# - Engine canonical research.json dosyasına YAZMAZ.
# - Deterministik Legal Knowledge Engine (provision_repository +
#   provision_version_policy + provision_policy) her zaman
#   çalışır ve source of truth / safety boundary'dir.
# - Agent (legal_research_agent.py, LLM tabanlı) VARSAYILAN
#   OLARAK KAPALIDIR. Açıldığında yalnız EK "agent_suggestion"
#   candidate önerir; formal/applicability/version çözümüne
#   ASLA karışmaz.
# - Agent LLM çağrısı başarısız olursa veya bir candidate
#   grounding/blocklist/free-text-safety kontrolünden geçemezse
#   FAIL-CLOSED davranılır: yalnız agent katmanı düşer,
#   deterministik candidate'lar etkilenmez.
# - Gerçek network çağrısı için İKİ açık gate gerekir:
#   --with-agent VE --allow-network.
# - Validator PASS olmadan pending yazılmaz.
# - Post-write validator tekrar çalışır.
# - Önceki pending varsa sessizce ezilmez; history'ye alınır.
# ============================================================


import argparse
import hashlib
import json
import os
import shutil
import sys

from datetime import datetime
from pathlib import Path

import path_containment

from timeline_validator import (
    load_canonical_fact_index,
)

from deadline_validator import (
    load_canonical_timeline,
)

from legal_research_policy import (
    LEGAL_RESEARCH_POLICY_VERSION,
    finalize_candidates,
    load_legal_documents_index,
    run_all_rules,
)

from legal_research_discovery import (
    LEGAL_RESEARCH_DISCOVERY_VERSION,
    run_discovery_for_uncovered_issues,
)

from legal_research_validator import (
    load_canonical_deadline_index,
    load_canonical_issues,
    validate_research_analysis,
)

from legal_research_agent import (
    LEGAL_RESEARCH_AGENT_VERSION,
    generate_agent_candidates,
)

from issue_spotting_validator import (
    FORBIDDEN_PHRASES,
)

from timeline_consolidation_policy import (
    normalize_text_tr,
)


# ============================================================
# VERSION
# ============================================================

LEGAL_RESEARCH_ENGINE_VERSION = "1"

# ROW 19C-3c-iv SLICE 1: generation-audit record'un action_family/schema
# sabitleri - `ui.services.legal_research_case_law_mutation_facade`'in
# KENDİ, bağımsız `legal_research_case_law_action_family_for("legal_research")`
# formülüyle BİREBİR aynı string.
GENERATION_ACTION_FAMILY = "generation.legal_research"

GENERATION_AUDIT_SCHEMA_VERSION = "1"


# ============================================================
# PATHS
# ============================================================

BASE_DIR = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

DATA_DIR = (
    BASE_DIR
    / "data"
)

CASES_DIR = (
    DATA_DIR
    / "cases"
)

DEFAULT_CASE_ID = "case_0001"


# ============================================================
# EXCEPTION
# ============================================================

class LegalResearchEngineError(
    Exception
):
    pass


# ============================================================
# JSON HELPERS
# ============================================================

def load_json(
    path,
):

    path = Path(
        path
    )

    if not path.exists():

        raise FileNotFoundError(
            f"JSON dosyası bulunamadı:\n{path}"
        )

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:

        return json.load(
            file
        )


def atomic_write_json(
    path,
    data,
):

    path = Path(
        path
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_path = (
        path.parent
        / (
            path.name
            + ".tmp"
        )
    )

    with open(
        temp_path,
        "w",
        encoding="utf-8",
        newline="\n",
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )

        file.write(
            "\n"
        )

        file.flush()

        os.fsync(
            file.fileno()
        )

    os.replace(
        temp_path,
        path,
    )


# ============================================================
# CASE PATHS
# ============================================================

def get_case_research_dir(
    case_id,
):

    return (
        CASES_DIR
        / case_id
        / "research"
    )


def get_pending_path(
    case_id,
):

    return (
        get_case_research_dir(
            case_id
        )
        / (
            f"legal_research_{case_id}_v1.json.pending"
        )
    )


def get_canonical_path(
    case_id,
):

    return (
        get_case_research_dir(
            case_id
        )
        / "research.json"
    )


def get_history_dir(
    case_id,
):

    return (
        get_case_research_dir(
            case_id
        )
        / "history"
    )


def get_reviews_dir(
    case_id,
):

    return (
        get_case_research_dir(
            case_id
        )
        / "generation_reviews"
    )


def get_target_ref():
    """Legal research generation case-scopludur - `ui.services.legal_
    research_case_law_mutation_facade.legal_research_case_law_target_
    ref_for("legal_research")` ile BİREBİR aynı string."""

    return "legal_research.pending"


# ============================================================
# PREVIOUS PENDING PRESERVATION
# ============================================================

def preserve_previous_pending(
    case_id,
    pending_path,
    *,
    history_dir=None,
):
    """`history_dir` additive/keyword-only: `None` iken (legacy/artık
    kapalı direct-CLI çağrısı) davranış bugüne kadar olduğu gibi
    `get_history_dir(case_id)`'den türetilir; coordinated path (ROW
    19C-3c-iv) altında facade'in lock-altında doğrulamış olduğu
    `VerifiedLegalResearchCaseLawOutputPaths.history_dir`'i açıkça
    geçirir - engine bu durumda kendi ham getter'ını I/O için ÇAĞIRMAZ."""

    pending_path = Path(
        pending_path
    )

    if not pending_path.exists():

        return None

    if history_dir is None:

        history_dir = (
            get_history_dir(
                case_id
            )
        )

    history_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = (
        datetime.now()
        .astimezone()
        .strftime(
            "%Y%m%d_%H%M%S"
        )
    )

    history_path = (
        history_dir
        / (
            "legal_research_pending_before_engine_"
            + timestamp
            + ".json.pending"
        )
    )

    shutil.move(
        str(
            pending_path
        ),
        str(
            history_path
        ),
    )

    return history_path


# ============================================================
# OUTPUT SEMANTIC GUARD (DEFENSE IN DEPTH)
# ============================================================

def validate_engine_output_semantics(
    analysis,
):

    if not isinstance(
        analysis,
        dict,
    ):

        raise LegalResearchEngineError(
            "Research analysis dict değil."
        )

    research_candidates = analysis.get(
        "research_candidates"
    )

    if not isinstance(
        research_candidates,
        list,
    ):

        raise LegalResearchEngineError(
            "research_candidates alanı list değil."
        )

    for research in research_candidates:

        if not isinstance(
            research,
            dict,
        ):

            raise LegalResearchEngineError(
                "Research kaydı dict değil."
            )

        if (
            research.get(
                "status"
            )
            != "candidate"
        ):

            raise LegalResearchEngineError(
                "Legal Research Engine yalnız "
                "status='candidate' üretebilir."
            )

        if (
            research.get(
                "research_type"
            )
            == "agent_suggestion"
            and (
                research.get(
                    "formal_result"
                )
                is not None
                or research.get(
                    "applicability_result"
                )
                is not None
                or research.get(
                    "resolved_provision_ids"
                )
            )
        ):

            raise LegalResearchEngineError(
                "Agent-sourced research candidate "
                "formal_result/applicability_result/"
                "resolved_provision_ids dolduramaz: "
                f"{research.get('research_id')}"
            )

        total_sources = (
            len(
                research.get(
                    "source_fact_ids",
                    [],
                )
            )
            + len(
                research.get(
                    "source_timeline_event_ids",
                    [],
                )
            )
            + len(
                research.get(
                    "source_deadline_ids",
                    [],
                )
            )
        )

        if (
            total_sources == 0
            and not research.get(
                "citation_refs"
            )
        ):

            raise LegalResearchEngineError(
                "Kaynaksız research candidate üretildi: "
                f"{research.get('research_id')}"
            )

        combined = normalize_text_tr(
            " ".join(
                [
                    str(
                        research.get(
                            "title",
                            "",
                        )
                    ),

                    str(
                        research.get(
                            "description",
                            "",
                        )
                    ),
                ]
            )
        )

        for phrase in FORBIDDEN_PHRASES:

            if phrase in combined:

                raise LegalResearchEngineError(
                    "Research candidate kesin hukuki "
                    f"sonuç ifadesi içeriyor ('{phrase}'): "
                    f"{research.get('research_id')}"
                )


# ============================================================
# BUILD
# ============================================================

def build_research_engine_output(
    case_id,
    use_agent=False,
    llm_client=None,
    use_discovery=False,
    retrieval_fn=None,
    network_allowed=False,
):

    fact_context = (
        load_canonical_fact_index(
            case_id
        )
    )

    fact_index = fact_context[
        "facts"
    ]

    timeline_context = (
        load_canonical_timeline(
            case_id
        )
    )

    event_index = timeline_context[
        "events"
    ]

    (
        deadline_index,
        deadline_ids,
        deadline_path,
    ) = (
        load_canonical_deadline_index(
            case_id
        )
    )

    issue_context = (
        load_canonical_issues(
            case_id
        )
    )

    issues = issue_context[
        "issues"
    ]

    issue_index = issue_context[
        "issue_index"
    ]

    documents_index = (
        load_legal_documents_index()
    )

    raw_candidates = (
        run_all_rules(
            issues=
                issues,

            fact_index=
                fact_index,

            deadline_index=
                deadline_index,

            documents_index=
                documents_index,
        )
    )

    deterministic_candidates = (
        finalize_candidates(
            raw_candidates
        )
    )

    research_candidates = list(
        deterministic_candidates
    )

    warnings = []

    if not deadline_path.exists():

        warnings.append(
            "Canonical deadline analysis bulunamadı; "
            "deadline tabanlı research kuralları "
            "atlanmıştır."
        )

    # ========================================================
    # OPTIONAL ISSUE-DRIVEN DISCOVERY LAYER
    #
    # Deterministik R1/R2 (explicit citation) HERHANGİ bir
    # candidate ÜRETMEDİĞİ issue'lar için, mevcut
    # query_parser + retriever altyapısı üzerinden retrieval
    # tabanlı araştırma dener. Retrieval de bir network
    # bağımlılığı (OpenAI embeddings + FAISS) taşıdığı için
    # AYNI network_allowed gate'i kullanır.
    # ========================================================

    covered_issue_ids = {
        candidate[
            "source_issue_id"
        ]
        for candidate
        in deterministic_candidates
    }

    discovery_stats = {
        "enabled":
            bool(
                use_discovery
            ),

        "uncovered_issue_count":
            len(
                [
                    issue
                    for issue in issues
                    if issue[
                        "issue_id"
                    ]
                    not in covered_issue_ids
                ]
            ),

        "candidate_count":
            0,
    }

    if use_discovery:

        (
            discovery_raw_candidates,
            discovery_warnings,
        ) = (
            run_discovery_for_uncovered_issues(
                issues=
                    issues,

                covered_issue_ids=
                    covered_issue_ids,

                event_index=
                    event_index,

                documents_index=
                    documents_index,

                retrieval_fn=
                    retrieval_fn,

                network_allowed=
                    network_allowed,
            )
        )

        discovery_candidates = (
            finalize_candidates(
                discovery_raw_candidates,

                start_index=
                    len(
                        deterministic_candidates
                    )
                    + 1,
            )
        )

        research_candidates = (
            deterministic_candidates
            + discovery_candidates
        )

        warnings.extend(
            discovery_warnings
        )

        discovery_stats[
            "candidate_count"
        ] = len(
            discovery_candidates
        )

    # ========================================================
    # OPTIONAL AGENT LAYER (LLM, EK RESEARCH CANDIDATE)
    # ========================================================

    agent_stats = {
        "enabled":
            bool(
                use_agent
            ),

        "raw_candidate_count":
            0,

        "accepted_count":
            0,

        "rejected_count":
            0,
    }

    if use_agent:

        (
            agent_candidates,
            agent_warnings,
            raw_stats,
        ) = (
            generate_agent_candidates(
                case_id=
                    case_id,

                issue_index=
                    issue_index,

                fact_index=
                    fact_index,

                event_index=
                    event_index,

                deadline_index=
                    deadline_index,

                start_index=
                    len(
                        research_candidates
                    )
                    + 1,

                existing_titles=[
                    research[
                        "title"
                    ]
                    for research
                    in research_candidates
                ],

                llm_client=
                    llm_client,

                network_allowed=
                    network_allowed,
            )
        )

        research_candidates = (
            research_candidates
            + agent_candidates
        )

        warnings.extend(
            agent_warnings
        )

        agent_stats.update(
            raw_stats
        )

    status = (
        "completed"
        if issues
        else "failed"
    )

    analysis = {
        "schema_version":
            1,

        "research_analysis_id":
            f"legal_research_{case_id}_v1",

        "case_id":
            case_id,

        "status":
            status,

        "generated_at":
            datetime.now()
            .astimezone()
            .isoformat(),

        "research_candidates":
            research_candidates,

        "warnings":
            warnings,

        "notes":
            (
                "Legal Research Engine V1 çekirdeği "
                "(deterministik Legal Knowledge Engine: "
                "provision_repository + "
                "provision_version_policy + "
                "provision_policy) canonical issues.json "
                "içindeki her issue için hukuki dayanak "
                "atıflarını çözümler ve source of truth / "
                "safety boundary'dir. "
                + (
                    "Bu çalıştırmada Legal Research Agent "
                    "V1 (LLM) da etkinleştirilmiştir; agent "
                    "yalnız EK 'agent_suggestion' candidate "
                    "önerebilir, formal/applicability/"
                    "version çözümüne karışamaz. "
                    if use_agent
                    else "Bu çalıştırmada Legal Research "
                    "Agent (LLM) devre dışıdır; yalnız "
                    "deterministik Legal Knowledge Engine "
                    "sorgulaması uygulanmıştır. "
                )
                + (
                    "Bu çalıştırmada Issue-Driven "
                    "Discovery V1 (query_parser + "
                    "retriever üzerinden retrieval) da "
                    "etkinleştirilmiştir; açık citation "
                    "taşımayan issue'lar için Legal "
                    "Knowledge Engine'de retrieval tabanlı "
                    "araştırma denenmiştir. "
                    if use_discovery
                    else "Bu çalıştırmada Issue-Driven "
                    "Discovery devre dışıdır; yalnız açık "
                    "(explicit) citation taşıyan issue'lar "
                    "işlenmiştir. "
                )
                + "Üretilen kayıtlar (kaynağı ne olursa "
                "olsun) research candidate'tır; hükmün "
                "yürürlükte olduğunu, uygulanabilir "
                "olduğunu, davanın sonucunu veya kesin bir "
                "hukuki sonucu kesinleştirmez."
            ),
    }

    validate_engine_output_semantics(
        analysis
    )

    discovery_candidate_count = (
        discovery_stats[
            "candidate_count"
        ]
    )

    return {
        "analysis":
            analysis,

        "issue_count":
            len(
                issue_index
            ),

        "fact_count":
            len(
                fact_index
            ),

        "timeline_event_count":
            len(
                event_index
            ),

        "deadline_count":
            len(
                deadline_ids
            ),

        "deterministic_candidate_count":
            len(
                deterministic_candidates
            ),

        "discovery_candidate_count":
            discovery_candidate_count,

        "agent_candidate_count":
            len(
                research_candidates
            )
            - len(
                deterministic_candidates
            )
            - discovery_candidate_count,

        "discovery_stats":
            discovery_stats,

        "agent_stats":
            agent_stats,
    }


# ============================================================
# ROW 19C-3c-iv SLICE 1 - GENERATION AUDIT RECORD SERIALIZATION
#
# `_canonical_json_bytes()`: `deadline_engine.py`'nin KENDİ, ALREADY-
# LOCKED yardımcısının bağımsız kopyası - bilinçli olarak pending
# dosyasının `atomic_write_json()` tarifinden FARKLIDIR (`os.linesep`
# çevrimi UYGULANIR; pending ise HER ZAMAN LF-only'dir, `newline="\n"`
# ile). Bu SADECE `*.generation_audit.json` dosyası için kullanılır.
# ============================================================

def _canonical_json_bytes(
    data,
):

    text = json.dumps(
        data,
        ensure_ascii=False,
        indent=2,
    )

    return text.replace(
        "\n",
        os.linesep,
    ).encode("utf-8")


def _write_generation_audit_record_excl(
    reviews_dir,
    audit_record,
):
    """`issue_spotting_engine._write_generation_audit_record_excl()` ile
    AYNI desen - zaman damgalı taban ad + `O_CREAT|O_EXCL` + sayısal
    sonek; sabit adın ÜZERİNE YAZMA sınıfı kapatılır, replay/
    reconciliation eşleşmesi HER ZAMAN içerikten yapılır, addan asla."""

    reviews_dir = Path(
        reviews_dir
    )

    reviews_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    stamp = (
        datetime.now()
        .strftime(
            "%Y%m%d_%H%M%S"
        )
    )

    base = f"legal_research_{stamp}"

    suffix = 0

    while True:

        if suffix == 0:
            name = f"{base}.generation_audit.json"
        else:
            name = f"{base}_{suffix}.generation_audit.json"

        path_containment.validate_segment(name)

        candidate = path_containment.resolve_for_create(
            reviews_dir,
            name,
        )

        try:
            fd = os.open(
                candidate,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError:
            suffix += 1
            if suffix > 1000:
                raise RuntimeError(
                    "Generation audit dosya adı için 1000 denemede "
                    "boş ad bulunamadı."
                )
            continue

        with os.fdopen(fd, "wb") as file:
            file.write(_canonical_json_bytes(audit_record))

        return candidate


# ============================================================
# WRITE PENDING
# ============================================================

def write_pending(
    case_id,
    analysis,
    *,
    verified_paths=None,
    input_digest=None,
    identity_payload=None,
    mutation_idempotency_key=None,
    mutation_resource_key=None,
    mutation_actor_ref=None,
):
    """ROW 19C-3c-iv SLICE 1: `verified_paths`/`input_digest`/`identity_
    payload`/`mutation_idempotency_key`/`mutation_resource_key`/
    `mutation_actor_ref` hepsi additive, keyword-only, varsayılan
    `None`. Hiçbiri verilmezse (legacy/artık kapalı direct-CLI çağrısı)
    davranış byte-for-byte KORUNUR - yalnız dönüş şekli dict'tir (diğer
    ailelerin AYNI, önceden LOCKED dönüşümüyle tutarlı). `mutation_
    idempotency_key is not None` -> mutation_binding_provided; bu
    durumda diğer dördü de ZORUNLUDUR (kısmi mutation-binding kabul
    edilmez)."""

    mutation_binding_provided = (
        mutation_idempotency_key is not None
    )

    if mutation_binding_provided:

        if (
            input_digest is None
            or identity_payload is None
            or mutation_resource_key is None
            or mutation_actor_ref is None
        ):

            raise LegalResearchEngineError(
                "mutation_idempotency_key verildiğinde input_digest/"
                "identity_payload/mutation_resource_key/"
                "mutation_actor_ref de verilmelidir (kısmi "
                "mutation-binding kabul edilmez)."
            )

    if verified_paths is not None:

        research_dir = verified_paths.family_root
        pending_path = verified_paths.pending_path
        history_dir_override = verified_paths.history_dir
        reviews_dir = verified_paths.reviews_dir

    else:

        research_dir = get_case_research_dir(case_id)
        pending_path = get_pending_path(case_id)
        history_dir_override = None
        reviews_dir = get_reviews_dir(case_id)

    research_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    canonical_path = (
        get_canonical_path(
            case_id
        )
    )

    canonical_exists_before = (
        canonical_path.exists()
    )

    previous_pending_history = (
        preserve_previous_pending(
            case_id=
                case_id,

            pending_path=
                pending_path,

            history_dir=
                history_dir_override,
        )
    )

    try:

        atomic_write_json(
            pending_path,
            analysis,
        )

        validation = (
            validate_research_analysis(
                research_path=
                    pending_path,

                expected_case_id=
                    case_id,

                raise_on_error=
                    True,
            )
        )

        if (
            validation.get(
                "valid"
            )
            is not True
        ):

            raise LegalResearchEngineError(
                "Post-write Legal Research Validator "
                "valid=False."
            )

        pending_raw_bytes = pending_path.read_bytes()

        pending_sha256 = hashlib.sha256(
            pending_raw_bytes
        ).hexdigest()

        written = json.loads(
            pending_raw_bytes.decode("utf-8")
        )

        validate_engine_output_semantics(
            written
        )

        if (
            canonical_exists_before
            != canonical_path.exists()
        ):

            raise LegalResearchEngineError(
                "Legal Research Engine canonical "
                "research.json durumunu değiştirdi."
            )

        audit_path = None

        first_write = (
            previous_pending_history
            is None
        )

        if mutation_binding_provided:

            history_backup_path = None

            history_backup_sha256 = None

            if not first_write:

                history_backup_path = str(
                    previous_pending_history
                )

                history_backup_sha256 = hashlib.sha256(
                    previous_pending_history.read_bytes()
                ).hexdigest()

            audit_record = {
                "schema_version": GENERATION_AUDIT_SCHEMA_VERSION,
                "case_id": case_id,
                "target_ref": get_target_ref(),
                "target_state": "generated",
                "action_family": GENERATION_ACTION_FAMILY,
                "channel": "local_lawyer_legal_research_case_law_cli",
                "mutation_actor_ref": mutation_actor_ref,
                "mutation_idempotency_key": mutation_idempotency_key,
                "mutation_resource_key": mutation_resource_key,
                "input_digest": input_digest,
                "generation_parameters_digest": None,
                "generation_mode": identity_payload.get("generation_mode"),
                "model_id": identity_payload.get("model_id"),
                "engine_version": identity_payload.get("engine_version"),
                "prompt_agent_version": identity_payload.get("prompt_agent_version"),
                "identity_payload": identity_payload,
                "first_write": first_write,
                "history_backup_path": history_backup_path,
                "history_backup_sha256": history_backup_sha256,
                "pending_sha256": pending_sha256,
                "generated_at": written.get("generated_at"),
                "outcome": "generated",
                "written_at": (
                    datetime.now()
                    .astimezone()
                    .isoformat()
                ),
            }

            audit_path = _write_generation_audit_record_excl(
                reviews_dir=reviews_dir,
                audit_record=audit_record,
            )

        return {
            "pending_path": pending_path,
            "validation": validation,
            "previous_pending_history": previous_pending_history,
            "pending_sha256": pending_sha256,
            "audit_path": audit_path,
            "first_write": first_write,
        }

    except Exception:

        if pending_path.exists():

            pending_path.unlink()

        if (
            previous_pending_history
            is not None
            and previous_pending_history.exists()
        ):

            shutil.move(
                str(
                    previous_pending_history
                ),
                str(
                    pending_path
                ),
            )

        raise


# ============================================================
# RUN ENGINE
# ============================================================

def run_engine(
    case_id,
    use_agent=False,
    llm_client=None,
    use_discovery=False,
    retrieval_fn=None,
    network_allowed=False,
):

    case_dir = (
        CASES_DIR
        / case_id
    )

    if not case_dir.exists():

        raise FileNotFoundError(
            f"Case bulunamadı:\n{case_dir}"
        )

    build_result = (
        build_research_engine_output(
            case_id,
            use_agent=
                use_agent,

            llm_client=
                llm_client,

            use_discovery=
                use_discovery,

            retrieval_fn=
                retrieval_fn,

            network_allowed=
                network_allowed,
        )
    )

    analysis = build_result[
        "analysis"
    ]

    write_result = write_pending(
        case_id,
        analysis,
    )

    pending_path = write_result["pending_path"]
    validation = write_result["validation"]
    previous_pending_history = write_result["previous_pending_history"]

    return {
        "analysis":
            analysis,

        "pending_path":
            pending_path,

        "validation":
            validation,

        "previous_pending_history":
            previous_pending_history,

        "issue_count":
            build_result[
                "issue_count"
            ],

        "fact_count":
            build_result[
                "fact_count"
            ],

        "timeline_event_count":
            build_result[
                "timeline_event_count"
            ],

        "deadline_count":
            build_result[
                "deadline_count"
            ],

        "deterministic_candidate_count":
            build_result[
                "deterministic_candidate_count"
            ],

        "discovery_candidate_count":
            build_result[
                "discovery_candidate_count"
            ],

        "agent_candidate_count":
            build_result[
                "agent_candidate_count"
            ],

        "discovery_stats":
            build_result[
                "discovery_stats"
            ],

        "agent_stats":
            build_result[
                "agent_stats"
            ],
    }


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Vergi AI Legal Research Engine V1"
        )
    )

    parser.add_argument(
        "--case",
        dest="case_id",
        default=DEFAULT_CASE_ID,
    )

    parser.add_argument(
        "--with-agent",
        action="store_true",
        dest="with_agent",
        help=(
            "Legal Research Agent V1 (LLM) katmanını da "
            "çalıştır. Tek başına GERÇEK NETWORK ÇAĞRISI "
            "YAPMAZ; ayrıca --allow-network gerekir."
        ),
    )

    parser.add_argument(
        "--with-discovery",
        action="store_true",
        dest="with_discovery",
        help=(
            "Issue-Driven Discovery V1 (query_parser + "
            "retriever) katmanını da çalıştır - açık "
            "citation taşımayan issue'lar için retrieval "
            "dener. Tek başına GERÇEK NETWORK ÇAĞRISI "
            "YAPMAZ (retriever import bile edilmez); "
            "ayrıca --allow-network gerekir."
        ),
    )

    parser.add_argument(
        "--allow-network",
        action="store_true",
        dest="allow_network",
        help=(
            "İKİNCİ AÇIK GATE: --with-agent / "
            "--with-discovery ile birlikte verilmedikçe "
            "hiçbir gerçek Anthropic/OpenAI API çağrısı "
            "yapılmaz."
        ),
    )

    args = parser.parse_args()

    # ROW 19C-3c-iv SLICE 1: bu doğrudan CLI mutasyon yolu artık DEVRE
    # DIŞIDIR - coordinator/journal/authz entegrasyonu yalnız
    # `ui.cli_mutate generation --row-key legal_research ...` üzerinden
    # yaşar. build_research_engine_output()/write_pending()/run_engine()
    # KENDİLERİ DEĞİŞTİRİLMEDİ - yalnız BU executable giriş noktası
    # reddediliyor. SystemExit bir BaseException'dır ve bu dosyanın
    # `if __name__` sarmalayıcısının hiçbir try/except'i yoktur, bu
    # yüzden gerçek OS process exit code'u tam olarak 2'dir - hiçbir
    # zaman 0, hiçbir zaman düz bir `return`. Bu nokta case/file/
    # network/model erişiminden ÖNCEDİR.

    print(
        "HATA: Bu doğrudan CLI mutasyon yolu artık DEVRE DIŞIDIR (Row 19C-3c-iv).\n"
        "Gerçek üretim için: python -m ui.cli_mutate generation --case <CASE_ID> "
        "--row-key legal_research [--with-agent [--allow-network]] ...",
        file=sys.stderr,
    )

    raise SystemExit(2)

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - LEGAL RESEARCH ENGINE V1"
    )

    print(
        "======================================"
    )

    print()

    print(
        "Research candidate üretiliyor..."
    )

    print(
        "Engine:",
        LEGAL_RESEARCH_ENGINE_VERSION,
    )

    print(
        "Policy:",
        LEGAL_RESEARCH_POLICY_VERSION,
    )

    if args.with_agent and args.allow_network:

        agent_status = (
            LEGAL_RESEARCH_AGENT_VERSION
            + " (network açık - gerçek API çağrısı "
            "denenebilir)"
        )

    elif args.with_agent:

        agent_status = (
            LEGAL_RESEARCH_AGENT_VERSION
            + " (network KAPALI - --allow-network "
            "verilmedi; agent atlanacak)"
        )

    else:

        agent_status = "devre dışı"

    if args.with_discovery and args.allow_network:

        discovery_status = (
            LEGAL_RESEARCH_DISCOVERY_VERSION
            + " (network açık - gerçek retrieval "
            "denenebilir)"
        )

    elif args.with_discovery:

        discovery_status = (
            LEGAL_RESEARCH_DISCOVERY_VERSION
            + " (network KAPALI - --allow-network "
            "verilmedi; discovery atlanacak)"
        )

    else:

        discovery_status = "devre dışı"

    print(
        "Agent:",
        agent_status,
    )

    print(
        "Discovery:",
        discovery_status,
    )

    print(
        "Case:",
        args.case_id,
    )

    try:

        result = (
            run_engine(
                case_id=
                    args.case_id,

                use_agent=
                    args.with_agent,

                use_discovery=
                    args.with_discovery,

                network_allowed=
                    args.allow_network,
            )
        )

    except Exception as error:

        print()

        print(
            "ENGINE ERROR"
        )

        print(
            error
        )

        print()

        print(
            "======================================"
        )

        print(
            " LEGAL RESEARCH ENGINE V1: FAIL"
        )

        print(
            "======================================"
        )

        sys.exit(
            1
        )

    analysis = result[
        "analysis"
    ]

    validation = result[
        "validation"
    ]

    print()

    print(
        "RESEARCH ANALYSIS OLUŞTURULDU"
    )

    print(
        "Analysis ID:",
        analysis[
            "research_analysis_id"
        ],
    )

    print(
        "Canonical issue:",
        result[
            "issue_count"
        ],
    )

    print(
        "Canonical fact:",
        result[
            "fact_count"
        ],
    )

    print(
        "Canonical timeline event:",
        result[
            "timeline_event_count"
        ],
    )

    print(
        "Canonical deadline:",
        result[
            "deadline_count"
        ],
    )

    print(
        "Research candidate count (explicit-citation):",
        result[
            "deterministic_candidate_count"
        ],
    )

    print(
        "Research candidate count (issue-driven "
        "discovery):",
        result[
            "discovery_candidate_count"
        ],
    )

    print(
        "Research candidate count (agent):",
        result[
            "agent_candidate_count"
        ],
    )

    print(
        "Research candidate count (total):",
        len(
            analysis[
                "research_candidates"
            ]
        ),
    )

    if args.with_discovery:

        print(
            "Discovery stats:",
            result[
                "discovery_stats"
            ],
        )

    if args.with_agent:

        print(
            "Agent stats:",
            result[
                "agent_stats"
            ],
        )

    print(
        "Status:",
        analysis[
            "status"
        ],
    )

    print(
        "Validator:",
        (
            "PASS"
            if validation[
                "valid"
            ]
            else "FAIL"
        ),
    )

    print()

    for research in analysis[
        "research_candidates"
    ]:

        print(
            "-",
            research[
                "research_id"
            ],
            "|",
            "issue=" + research[
                "source_issue_id"
            ],
            "|",
            research[
                "finding_status"
            ],
            "|",
            research[
                "trigger_rule_id"
            ],
        )

        print(
            "  ",
            research[
                "title"
            ],
        )

    if analysis.get(
        "warnings"
    ):

        print()

        print(
            "Engine warnings:"
        )

        for warning in analysis[
            "warnings"
        ]:

            print(
                "-",
                warning,
            )

    if validation.get(
        "warnings"
    ):

        print()

        print(
            "Validator warnings:"
        )

        for warning in validation[
            "warnings"
        ]:

            print(
                "-",
                warning,
            )

    print()

    print(
        "Pending output:"
    )

    print(
        result[
            "pending_path"
        ]
    )

    if result[
        "previous_pending_history"
    ]:

        print()

        print(
            "Previous pending archived:"
        )

        print(
            result[
                "previous_pending_history"
            ]
        )

    print()

    print(
        "SAFETY CHECKS:"
    )

    print(
        "- Formal/applicability/version çözümü yalnız "
        "deterministik Legal Knowledge Engine "
        "tarafından yapılmıştır."
    )

    print(
        "- Discovery (retrieval):",
        discovery_status,
    )

    print(
        "- LLM (Agent):",
        agent_status,
    )

    print(
        "- LLM'e title/description yazdırılmaz; render "
        "yalnız deterministik template ile yapılır."
    )

    print(
        "- Issue-driven discovery bulduğu chunk'ı da "
        "provision_repository/version_policy/"
        "provision_policy üzerinden ayrıca çözer; hiçbir "
        "kaynak bulunamazsa finding_status="
        "'no_research_evidence' üretir (LLM bilgisi "
        "hukuki kaynak yerine kullanılmaz)."
    )

    print(
        "- Agent formal_result/applicability_result/"
        "resolved_provision_ids dolduramaz."
    )

    print(
        "- Kesin hukuki sonuç ifadesi üretilmemiştir."
    )

    print(
        "- Canonical research.json değiştirilmemiştir."
    )

    print()

    print(
        "======================================"
    )

    print(
        " LEGAL RESEARCH ENGINE V1: PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    main()
