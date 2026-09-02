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
# WRITE PENDING
# ============================================================

def write_pending(
    case_id,
    analysis,
):

    research_dir = (
        get_case_research_dir(
            case_id
        )
    )

    research_dir.mkdir(
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

        written = load_json(
            pending_path
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
