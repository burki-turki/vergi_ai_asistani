# ============================================================
# VERGİ AI - ISSUE SPOTTING ENGINE V1
#
# AMAÇ
# ----
#
# Canonical case facts + canonical timeline + (varsa) canonical
# deadline analysis üzerinden Issue Spotting Policy V1'i
# çalıştırmak ve sonucu:
#
#     data/cases/<case_id>/issues/
#     issue_spotting_<case_id>_v1.json.pending
#
# olarak üretmek.
#
#
# MİMARİ
# ------
#
# canonical facts + canonical timeline + canonical deadline
#        ↓
# Issue Spotting Policy V1 (deterministik kurallar)
#        ↓
# Issue Spotting Validator V1
#        ↓
# *.json.pending
#        ↓
# human approval
#        ↓
# canonical issues.json
#
#
# KRİTİK GÜVENLİK
# ----------------
#
# - Engine canonical issues.json dosyasına YAZMAZ.
# - Yalnız pending üretir.
# - Deterministik kurallar (issue_spotting_policy.py) her
#   zaman çalışır ve source of truth / safety boundary'dir.
# - Agent (issue_spotting_agent.py, LLM tabanlı) VARSAYILAN
#   OLARAK KAPALIDIR (use_agent=False / --with-agent
#   verilmezse). Açıldığında yalnız EK candidate önerir;
#   deterministik candidate'ları asla değiştirmez veya
#   override etmez.
# - Agent LLM çağrısı başarısız olursa veya bir candidate
#   grounding/blocklist kontrolünden geçemezse FAIL-CLOSED
#   davranılır: yalnız o candidate/agent katmanı düşer,
#   deterministik candidate'lar etkilenmez.
# - Üretilen kayıtlar (deterministik + agent) issue
#   candidate'tır: verified fact, legal conclusion, case
#   outcome, guaranteed applicability veya deadline
#   determination DEĞİLDİR.
# - Validator PASS olmadan pending yazılmaz (agent
#   candidate'lar dahil, tüm liste aynı validator'dan geçer).
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

from issue_spotting_policy import (
    ISSUE_SPOTTING_POLICY_VERSION,
    finalize_candidates,
    run_all_rules,
)

from issue_spotting_validator import (
    FORBIDDEN_PHRASES,
    load_canonical_deadline_optional,
    validate_issue_analysis,
)

from issue_spotting_agent import (
    ISSUE_SPOTTING_AGENT_VERSION,
    generate_agent_candidates,
)

from timeline_consolidation_policy import (
    normalize_text_tr,
)


# ============================================================
# VERSION
# ============================================================

ISSUE_SPOTTING_ENGINE_VERSION = "1"


# ============================================================
# ROW 19C-3c-ii - GENERATION MUTATION BINDING
#
# `deadline_engine.py`/`timeline_engine.py` (Row 19C-3c-i, LOCKED)
# ile AYNI additive desen: write_pending() legacy davranışını
# (mutation_idempotency_key verilmezse) byte-for-byte korur; yalnız
# coordinated path (ui.services.agent_generation_mutation_facade)
# mutation-binding kwargs'ı geçirdiğinde bir `*.generation_audit.json`
# kaydı üretir. GENERATION_AUDIT_SCHEMA_VERSION = "1" - deadline/
# timeline'ın KENDİ sabitiyle AYNI literal (paylaşılan bir modül
# import edilmez, her aile kendi sabitini taşır - ayrı, bağımsız
# şema/versiyon alanı).
# ============================================================

GENERATION_ACTION_FAMILY = "generation.issue_spotting"

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

class IssueSpottingEngineError(
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

def get_case_issues_dir(
    case_id,
):

    return (
        CASES_DIR
        / case_id
        / "issues"
    )


def get_pending_path(
    case_id,
):

    return (
        get_case_issues_dir(
            case_id
        )
        / (
            f"issue_spotting_{case_id}_v1.json.pending"
        )
    )


def get_canonical_path(
    case_id,
):

    return (
        get_case_issues_dir(
            case_id
        )
        / "issues.json"
    )


def get_history_dir(
    case_id,
):

    return (
        get_case_issues_dir(
            case_id
        )
        / "history"
    )


def get_reviews_dir(
    case_id,
):

    return (
        get_case_issues_dir(
            case_id
        )
        / "generation_reviews"
    )


def get_target_ref():
    """Issue spotting generation case-scopludur (deadline'ın anchor-bazlı
    şeklinin AKSİNE) - tek bir case için tek bir operasyon slotu, tıpkı
    `timeline_engine.get_target_ref()` gibi."""

    return "issue_spotting.pending"


# ============================================================
# PREVIOUS PENDING PRESERVATION
# ============================================================

def preserve_previous_pending(
    case_id,
    pending_path,
    *,
    history_dir=None,
):
    """`history_dir` additive/keyword-only: `None` iken (legacy/default)
    davranış bugüne kadar olduğu gibi `get_history_dir(case_id)`'den
    türetilir; coordinated path (ROW 19C-3c-ii) altında facade'in
    lock-altında doğrulamış olduğu `VerifiedGenerationOutputPaths.
    history_dir`'i açıkça geçirir - engine bu durumda kendi ham
    getter'ını I/O için ÇAĞIRMAZ."""

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
            "issue_spotting_pending_before_engine_"
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
# ROW 19C-3c-ii - GENERATION AUDIT RECORD SERIALIZATION
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
    """`deadline_engine._write_generation_audit_record_excl()` ile AYNI
    desen - zaman damgalı taban ad + `O_CREAT|O_EXCL` + sayısal sonek;
    sabit adın ÜZERİNE YAZMA sınıfı kapatılır, replay/reconciliation
    eşleşmesi HER ZAMAN içerikten yapılır, addan asla."""

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

    base = f"issue_spotting_{stamp}"

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
# OUTPUT SEMANTIC GUARD
#
# Validator'da yapılan kontrollerin engine seviyesinde de
# bağımsız bir kez daha uygulanması (defense in depth).
# ============================================================

def validate_engine_output_semantics(
    analysis,
):

    if not isinstance(
        analysis,
        dict,
    ):

        raise IssueSpottingEngineError(
            "Issue analysis dict değil."
        )

    issues = analysis.get(
        "issues"
    )

    if not isinstance(
        issues,
        list,
    ):

        raise IssueSpottingEngineError(
            "issues alanı list değil."
        )

    for issue in issues:

        if not isinstance(
            issue,
            dict,
        ):

            raise IssueSpottingEngineError(
                "Issue kaydı dict değil."
            )

        # ====================================================
        # CANDIDATE STATUS GUARD
        # ====================================================

        if (
            issue.get(
                "status"
            )
            != "candidate"
        ):

            raise IssueSpottingEngineError(
                "Issue Spotting Engine yalnız "
                "status='candidate' üretebilir. "
                "Verified fact veya legal conclusion "
                "üretimi yasaktır."
            )

        # ====================================================
        # SOURCE GUARD
        # ====================================================

        total_sources = (
            len(
                issue.get(
                    "source_fact_ids",
                    [],
                )
            )
            + len(
                issue.get(
                    "source_timeline_event_ids",
                    [],
                )
            )
            + len(
                issue.get(
                    "source_deadline_ids",
                    [],
                )
            )
        )

        if total_sources == 0:

            raise IssueSpottingEngineError(
                "Kaynaksız issue candidate üretildi: "
                f"{issue.get('issue_id')}"
            )

        # ====================================================
        # FORBIDDEN PHRASE GUARD
        # ====================================================

        combined = normalize_text_tr(
            " ".join(
                [
                    str(
                        issue.get(
                            "title",
                            "",
                        )
                    ),

                    str(
                        issue.get(
                            "description",
                            "",
                        )
                    ),
                ]
            )
        )

        for phrase in FORBIDDEN_PHRASES:

            if phrase in combined:

                raise IssueSpottingEngineError(
                    "Issue candidate kesin hukuki sonuç "
                    f"ifadesi içeriyor ('{phrase}'): "
                    f"{issue.get('issue_id')}"
                )


# ============================================================
# BUILD
# ============================================================

def build_issue_engine_output(
    case_id,
    use_agent=False,
    llm_client=None,
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

    timeline_events = list(
        event_index.values()
    )

    (
        deadlines,
        deadline_ids,
        deadline_path,
    ) = (
        load_canonical_deadline_optional(
            case_id
        )
    )

    raw_candidates = (
        run_all_rules(
            fact_index=
                fact_index,

            timeline_events=
                timeline_events,

            event_index=
                event_index,

            deadlines=
                deadlines,
        )
    )

    deterministic_issues = (
        finalize_candidates(
            raw_candidates
        )
    )

    issues = list(
        deterministic_issues
    )

    warnings = []

    if not deadline_path.exists():

        warnings.append(
            "Canonical deadline analysis bulunamadı; "
            "deadline tabanlı issue kuralları "
            "atlanmıştır."
        )

    # ========================================================
    # OPTIONAL AGENT LAYER (LLM, EK CANDIDATE)
    #
    # Deterministik issues listesi bu noktada zaten TAMDIR.
    # Agent yalnız SONUNA ekleme yapar; deterministik
    # candidate'ları asla değiştirmez/kaldırmaz. Agent
    # tamamen başarısız olsa bile issues == deterministic
    # issues olarak kalır (fail-closed).
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
            agent_issues,
            agent_warnings,
            raw_stats,
        ) = (
            generate_agent_candidates(
                case_id=
                    case_id,

                fact_index=
                    fact_index,

                event_index=
                    event_index,

                deadlines=
                    deadlines,

                start_index=
                    len(
                        deterministic_issues
                    )
                    + 1,

                existing_titles=[
                    issue[
                        "title"
                    ]
                    for issue
                    in deterministic_issues
                ],

                llm_client=
                    llm_client,

                network_allowed=
                    network_allowed,
            )
        )

        issues = (
            deterministic_issues
            + agent_issues
        )

        warnings.extend(
            agent_warnings
        )

        agent_stats.update(
            raw_stats
        )

    status = (
        "completed"
        if fact_index
        else "failed"
    )

    analysis = {
        "schema_version":
            1,

        "issue_analysis_id":
            f"issue_spotting_{case_id}_v1",

        "case_id":
            case_id,

        "status":
            status,

        "generated_at":
            datetime.now()
            .astimezone()
            .isoformat(),

        "issues":
            issues,

        "warnings":
            warnings,

        "notes":
            (
                "Issue Spotting Engine V1 çekirdeği "
                "(deterministik kurallar, "
                "issue_spotting_policy.py) canonical facts, "
                "canonical timeline ve (varsa) canonical "
                "deadline analysis üzerinden çalışır ve "
                "source of truth / safety boundary'dir. "
                + (
                    "Bu çalıştırmada Issue Spotting Agent "
                    "V1 (LLM, issue_spotting_agent.py) da "
                    "etkinleştirilmiştir; agent yalnız EK "
                    "candidate önerebilir, deterministik "
                    "candidate'ları değiştiremez, ve her "
                    "candidate canonical fact/timeline/"
                    "deadline referansına dayanmak "
                    "zorundadır (grounding check). "
                    if use_agent
                    else "Bu çalıştırmada Issue Spotting "
                    "Agent (LLM) devre dışıdır; yalnız "
                    "deterministik kurallar uygulanmıştır. "
                )
                + "Üretilen kayıtlar (kaynağı ne olursa "
                "olsun) issue candidate'tır; verified fact, "
                "legal conclusion, case outcome, guaranteed "
                "applicability veya deadline determination "
                "değildir."
            ),
    }

    validate_engine_output_semantics(
        analysis
    )

    return {
        "analysis":
            analysis,

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

        "deterministic_issue_count":
            len(
                deterministic_issues
            ),

        "agent_issue_count":
            len(
                issues
            )
            - len(
                deterministic_issues
            ),

        "agent_stats":
            agent_stats,
    }


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
    """ROW 19C-3c-ii: `verified_paths`/`input_digest`/`identity_payload`/
    `mutation_idempotency_key`/`mutation_resource_key`/`mutation_actor_ref`
    hepsi additive, keyword-only, varsayılan `None`. Hiçbiri verilmezse
    (legacy/self-test/artık kapalı direct-CLI çağrısı) davranış bugüne
    kadar olduğu gibi byte-for-byte KORUNUR - yalnız dönüş şekli TEK
    seferlik, kasıtlı bir değişiklikle tuple'dan dict'e döner (bkz.
    `deadline_engine.write_pending()`'in AYNI, önceden LOCKED dönüşümü).
    `mutation_idempotency_key is not None` -> mutation_binding_provided;
    bu durumda diğer dördü de ZORUNLUDUR (kısmi binding kabul edilmez).
    """

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

            raise IssueSpottingEngineError(
                "mutation_idempotency_key verildiğinde input_digest/"
                "identity_payload/mutation_resource_key/"
                "mutation_actor_ref de verilmelidir (kısmi "
                "mutation-binding kabul edilmez)."
            )

    if verified_paths is not None:

        issues_dir = verified_paths.family_root
        pending_path = verified_paths.pending_path
        history_dir_override = verified_paths.history_dir
        reviews_dir = verified_paths.reviews_dir

    else:

        issues_dir = get_case_issues_dir(case_id)
        pending_path = get_pending_path(case_id)
        history_dir_override = None
        reviews_dir = get_reviews_dir(case_id)

    issues_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    canonical_path = (
        get_canonical_path(
            case_id
        )
    )

    # ========================================================
    # CANONICAL FILE IS NEVER MODIFIED HERE
    # ========================================================

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

        # ====================================================
        # POST-WRITE VALIDATOR
        # ====================================================

        validation = (
            validate_issue_analysis(
                issue_path=
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

            raise IssueSpottingEngineError(
                "Post-write Issue Spotting Validator "
                "valid=False."
            )

        # ====================================================
        # RELOAD + SEMANTIC GUARD (GERÇEK DİSK BAYTLARINDAN)
        # ====================================================

        pending_raw_bytes = pending_path.read_bytes()

        pending_sha256 = hashlib.sha256(pending_raw_bytes).hexdigest()

        written = json.loads(
            pending_raw_bytes.decode("utf-8")
        )

        validate_engine_output_semantics(
            written
        )

        # ====================================================
        # CANONICAL MUTATION GUARD
        # ====================================================

        if (
            canonical_exists_before
            != canonical_path.exists()
        ):

            raise IssueSpottingEngineError(
                "Issue Spotting Engine canonical "
                "issues.json durumunu değiştirdi."
            )

        # ====================================================
        # GENERATION AUDIT RECORD (yalnız coordinator-mode'da)
        # ====================================================

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
                "channel": "local_lawyer_generation_cli",
                "mutation_actor_ref": mutation_actor_ref,
                "mutation_idempotency_key": mutation_idempotency_key,
                "mutation_resource_key": mutation_resource_key,
                "input_digest": input_digest,
                "generation_parameters_digest": None,
                "generation_mode": identity_payload.get("generation_mode"),
                "model_id": identity_payload.get("model_id"),
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
        build_issue_engine_output(
            case_id,
            use_agent=
                use_agent,

            llm_client=
                llm_client,

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

        "deterministic_issue_count":
            build_result[
                "deterministic_issue_count"
            ],

        "agent_issue_count":
            build_result[
                "agent_issue_count"
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
            "Vergi AI Issue Spotting Engine V1"
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
            "Issue Spotting Agent V1.1 (LLM) katmanını da "
            "çalıştır. Tek başına GERÇEK NETWORK ÇAĞRISI "
            "YAPMAZ; ayrıca --allow-network gerekir. "
            "ANTHROPIC_API_KEY gerekir; yoksa veya çağrı "
            "başarısız olursa fail-closed davranılır ve "
            "deterministik candidate'lar korunur."
        ),
    )

    parser.add_argument(
        "--allow-network",
        action="store_true",
        dest="allow_network",
        help=(
            "İKİNCİ AÇIK GATE: --with-agent ile birlikte "
            "verilmedikçe hiçbir gerçek Anthropic API "
            "çağrısı yapılmaz (AnthropicIssueLLMClient dahi "
            "oluşturulmaz). Varsayılan: network yok, "
            "gerçek provider çağrısı yok."
        ),
    )

    args = parser.parse_args()

    # ROW 19C-3c-ii: bu doğrudan CLI mutasyon yolu artık DEVRE DIŞIDIR -
    # coordinator/journal/authz entegrasyonu yalnız `ui.cli_mutate
    # generation --row-key issue_spotting ...` üzerinden yaşar.
    # run_engine()/write_pending() KENDİLERİ DEĞİŞTİRİLMEDİ - yalnız BU
    # executable giriş noktası reddediliyor. SystemExit bir
    # BaseException'dır ve bu dosyanın `if __name__` sarmalayıcısının
    # hiçbir try/except'i yoktur, bu yüzden gerçek OS process exit code'u
    # tam olarak 2'dir - hiçbir zaman 0, hiçbir zaman düz bir `return`.

    print(
        "HATA: Bu doğrudan CLI mutasyon yolu artık DEVRE DIŞIDIR (Row 19C-3c-ii).\n"
        "Gerçek üretim için: python -m ui.cli_mutate generation --case <CASE_ID> "
        "--row-key issue_spotting ...",
        file=sys.stderr,
    )

    raise SystemExit(2)

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - ISSUE SPOTTING ENGINE V1"
    )

    print(
        "======================================"
    )

    print()

    print(
        "Issue candidate üretiliyor..."
    )

    print(
        "Engine:",
        ISSUE_SPOTTING_ENGINE_VERSION,
    )

    print(
        "Policy:",
        ISSUE_SPOTTING_POLICY_VERSION,
    )

    if args.with_agent and args.allow_network:

        agent_status = (
            ISSUE_SPOTTING_AGENT_VERSION
            + " (network açık - gerçek API çağrısı "
            "denenebilir)"
        )

    elif args.with_agent:

        agent_status = (
            ISSUE_SPOTTING_AGENT_VERSION
            + " (network KAPALI - --allow-network "
            "verilmedi; agent atlanacak, gerçek çağrı "
            "yapılmayacak)"
        )

    else:

        agent_status = "devre dışı"

    print(
        "Agent:",
        agent_status,
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

                network_allowed=
                    args.allow_network,

                use_agent=
                    args.with_agent,
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
            " ISSUE SPOTTING ENGINE V1: FAIL"
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
        "ISSUE ANALYSIS OLUŞTURULDU"
    )

    print(
        "Analysis ID:",
        analysis[
            "issue_analysis_id"
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
        "Issue candidate count (deterministic):",
        result[
            "deterministic_issue_count"
        ],
    )

    print(
        "Issue candidate count (agent):",
        result[
            "agent_issue_count"
        ],
    )

    print(
        "Issue candidate count (total):",
        len(
            analysis[
                "issues"
            ]
        ),
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

    for issue in analysis[
        "issues"
    ]:

        print(
            "-",
            issue[
                "issue_id"
            ],
            "|",
            issue[
                "issue_type"
            ],
            "|",
            issue[
                "trigger_rule_id"
            ],
        )

        print(
            "  ",
            issue[
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
        "- LLM (Agent):",
        agent_status,
    )

    print(
        "- LLM'e title/description yazdırılmaz; render "
        "yalnız deterministik template ile yapılır."
    )

    print(
        "- Deterministik candidate'lar agent'tan "
        "bağımsız olarak korunmuştur."
    )

    print(
        "- Tüm issue candidate'lar status='candidate'."
    )

    print(
        "- Kesin hukuki sonuç ifadesi üretilmemiştir."
    )

    print(
        "- Canonical issues.json değiştirilmemiştir."
    )

    print()

    print(
        "======================================"
    )

    print(
        " ISSUE SPOTTING ENGINE V1: PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    main()
