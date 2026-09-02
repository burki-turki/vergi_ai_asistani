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
import json
import os
import shutil
import sys

from datetime import datetime
from pathlib import Path


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


# ============================================================
# PREVIOUS PENDING PRESERVATION
# ============================================================

def preserve_previous_pending(
    case_id,
    pending_path,
):

    pending_path = Path(
        pending_path
    )

    if not pending_path.exists():

        return None

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
):

    issues_dir = (
        get_case_issues_dir(
            case_id
        )
    )

    issues_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    pending_path = (
        get_pending_path(
            case_id
        )
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
        # RELOAD + SEMANTIC GUARD
        # ====================================================

        written = load_json(
            pending_path
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

        return (
            pending_path,
            validation,
            previous_pending_history,
        )

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

    (
        pending_path,
        validation,
        previous_pending_history,
    ) = write_pending(
        case_id,
        analysis,
    )

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
