# ============================================================
# VERGİ AI - CASE LAW ENGINE V2
#
# AMAÇ
# ----
#
# Canonical issues.json (Row 9) + canonical research.json
# (Row 10) üzerinden Case Law Policy V2'yi (deterministik
# intent building) ve Case Law Discovery V2'yi (query_parser +
# retriever üzerinden retrieval) çalıştırıp sonucu:
#
#     data/cases/<case_id>/case_law/
#     case_law_<case_id>_v1.json.pending
#
# olarak üretmek.
#
#
# MİMARİ (V2 - COVERAGE / DECISION AYRIMI)
# --------------------------------------------
#
# canonical issues + canonical research
#        ↓
# Case Law Policy V2 (build_case_law_intent)
#        ↓
# Case Law Discovery V2 (query_parser + retriever)
#        ↓
# HER issue için 1 coverage kaydı + 0..N decision kaydı
#        ↓
# Case Law Validator V2
#        ↓
# *.json.pending
#        ↓
# human approval
#        ↓
# canonical case_law.json
#
#
# KRİTİK GÜVENLİK
# ----------------
#
# - Engine canonical case_law.json dosyasına YAZMAZ.
# - HER canonical issue için TAM OLARAK BİR coverage kaydı
#   üretilir - sessiz coverage boşluğu ENGELLENİR.
# - Bir issue için 0..N GROUNDED decision kaydı olabilir;
#   retrieval sıralaması hukuki üstünlük ifade ETMEZ.
# - Aynı source_document_id aynı issue altında yalnız BİR
#   decision üretir (dedup).
# - court_name/court_unit/case_number/decision_number/
#   decision_date/source_url YALNIZ canonical documents.json'
#   daki gerçek bir "Yargı Kararı" kaydından gelebilir ve onunla
#   BİREBİR eşleşmelidir.
# - Agent (case_law_agent.py, LLM) VARSAYILAN OLARAK KAPALIDIR;
#   açıldığında yalnız case_law_agent_suggestions dizisine EK
#   kayıt ekler - coverage/decision alanlarına ASLA karışamaz.
# - Gerçek network çağrısı (retrieval VEYA LLM) için
#   --allow-network şarttır; --with-agent tek başına yetmez.
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


from deadline_validator import (
    load_canonical_timeline,
)

from legal_research_validator import (
    load_canonical_issues,
)

from case_law_policy import (
    CASE_LAW_POLICY_VERSION,
    build_case_law_intent,
    finalize_coverage,
    finalize_decisions,
    finalize_agent_suggestions,
    load_legal_documents_index,
)

from case_law_discovery import (
    CASE_LAW_DISCOVERY_VERSION,
    run_case_law_discovery_for_issues,
)

from case_law_validator import (
    load_canonical_research,
    validate_case_law_analysis,
)

from case_law_agent import (
    CASE_LAW_AGENT_VERSION,
    generate_agent_candidates,
)

from issue_spotting_validator import (
    FORBIDDEN_PHRASES,
)

from case_law_policy import (
    CASE_LAW_FORBIDDEN_PHRASES,
)

from timeline_consolidation_policy import (
    normalize_text_tr,
)


# ============================================================
# VERSION
# ============================================================

CASE_LAW_ENGINE_VERSION = "2"

ALL_FORBIDDEN_PHRASES = (
    tuple(
        FORBIDDEN_PHRASES
    )
    + tuple(
        CASE_LAW_FORBIDDEN_PHRASES
    )
)


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

class CaseLawEngineError(
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

def get_case_law_dir(
    case_id,
):

    return (
        CASES_DIR
        / case_id
        / "case_law"
    )


def get_pending_path(
    case_id,
):

    return (
        get_case_law_dir(
            case_id
        )
        / (
            f"case_law_{case_id}_v1.json.pending"
        )
    )


def get_canonical_path(
    case_id,
):

    return (
        get_case_law_dir(
            case_id
        )
        / "case_law.json"
    )


def get_history_dir(
    case_id,
):

    return (
        get_case_law_dir(
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
            "case_law_pending_before_engine_"
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

def check_forbidden_phrases(
    record_id,
    title,
    description,
):

    combined = normalize_text_tr(
        f"{title or ''} {description or ''}"
    )

    for phrase in ALL_FORBIDDEN_PHRASES:

        if phrase in combined:

            raise CaseLawEngineError(
                "Kayıt kesin hukuki sonuç/case outcome "
                f"ifadesi içeriyor ('{phrase}'): "
                f"{record_id}"
            )


def validate_engine_output_semantics(
    analysis,
    expected_issue_count,
):

    if not isinstance(
        analysis,
        dict,
    ):

        raise CaseLawEngineError(
            "Case law analysis dict değil."
        )

    coverage_records = analysis.get(
        "case_law_coverage"
    )

    decision_records = analysis.get(
        "case_law_decisions"
    )

    suggestion_records = analysis.get(
        "case_law_agent_suggestions"
    )

    if not isinstance(
        coverage_records,
        list,
    ):

        raise CaseLawEngineError(
            "case_law_coverage alanı list değil."
        )

    if not isinstance(
        decision_records,
        list,
    ):

        raise CaseLawEngineError(
            "case_law_decisions alanı list değil."
        )

    if not isinstance(
        suggestion_records,
        list,
    ):

        raise CaseLawEngineError(
            "case_law_agent_suggestions alanı list değil."
        )

    covered_issue_ids = set()

    for coverage in coverage_records:

        if not isinstance(
            coverage,
            dict,
        ):

            raise CaseLawEngineError(
                "Coverage kaydı dict değil."
            )

        if (
            coverage.get(
                "status"
            )
            != "candidate"
            or coverage.get(
                "requires_human_review"
            )
            is not True
        ):

            raise CaseLawEngineError(
                "Coverage kaydı status/"
                "requires_human_review kısıtını ihlal "
                f"ediyor: {coverage.get('coverage_id')}"
            )

        check_forbidden_phrases(
            coverage.get(
                "coverage_id"
            ),

            coverage.get(
                "title"
            ),

            coverage.get(
                "description"
            ),
        )

        covered_issue_ids.add(
            coverage.get(
                "source_issue_id"
            )
        )

    if (
        len(
            covered_issue_ids
        )
        != expected_issue_count
        or len(
            coverage_records
        )
        != expected_issue_count
    ):

        raise CaseLawEngineError(
            "Her canonical issue tam olarak bir coverage "
            f"kaydı almalıdır. Beklenen="
            f"{expected_issue_count}, "
            f"Bulunan (benzersiz issue)="
            f"{len(covered_issue_ids)}, "
            f"Bulunan (toplam kayıt)="
            f"{len(coverage_records)}"
        )

    seen_document_ids_by_issue = {}

    for decision in decision_records:

        if not isinstance(
            decision,
            dict,
        ):

            raise CaseLawEngineError(
                "Decision kaydı dict değil."
            )

        if (
            decision.get(
                "status"
            )
            != "candidate"
            or decision.get(
                "requires_human_review"
            )
            is not True
        ):

            raise CaseLawEngineError(
                "Decision kaydı status/"
                "requires_human_review kısıtını ihlal "
                f"ediyor: {decision.get('decision_id')}"
            )

        if not decision.get(
            "source_document_id"
        ):

            raise CaseLawEngineError(
                "Decision kaydı source_document_id "
                f"taşımıyor: {decision.get('decision_id')}"
            )

        key = (
            decision.get(
                "source_issue_id"
            ),

            decision.get(
                "source_document_id"
            ),
        )

        if key in seen_document_ids_by_issue:

            raise CaseLawEngineError(
                "Aynı source_document_id aynı issue "
                f"altında DUPLICATE üretildi: {key}"
            )

        seen_document_ids_by_issue[
            key
        ] = True

        if (
            decision.get(
                "applicability_result"
            )
            not in (
                None,
                "unknown",
                "needs_review",
            )
        ):

            raise CaseLawEngineError(
                "Decision kaydı applicability_result "
                "yalnız null/'unknown'/'needs_review' "
                f"olabilir: {decision.get('decision_id')}"
            )

        check_forbidden_phrases(
            decision.get(
                "decision_id"
            ),

            decision.get(
                "title"
            ),

            decision.get(
                "description"
            ),
        )

    for suggestion in suggestion_records:

        if not isinstance(
            suggestion,
            dict,
        ):

            raise CaseLawEngineError(
                "Agent suggestion kaydı dict değil."
            )

        if (
            suggestion.get(
                "status"
            )
            != "candidate"
            or suggestion.get(
                "requires_human_review"
            )
            is not True
        ):

            raise CaseLawEngineError(
                "Agent suggestion status/"
                "requires_human_review kısıtını ihlal "
                f"ediyor: {suggestion.get('suggestion_id')}"
            )

        forbidden_keys = {
            "court_name",
            "court_unit",
            "case_number",
            "decision_number",
            "decision_date",
            "source_url",
            "source_document_id",
            "grounded_document_ids",
        } & set(
            suggestion.keys()
        )

        if forbidden_keys:

            raise CaseLawEngineError(
                "Agent suggestion court metadata alanı "
                f"taşıyor (yapısal ihlal): {forbidden_keys} "
                f"- {suggestion.get('suggestion_id')}"
            )

        check_forbidden_phrases(
            suggestion.get(
                "suggestion_id"
            ),

            suggestion.get(
                "title"
            ),

            suggestion.get(
                "description"
            ),
        )


# ============================================================
# BUILD
# ============================================================

def build_case_law_engine_output(
    case_id,
    use_agent=False,
    llm_client=None,
    retrieval_fn=None,
    network_allowed=False,
):

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

    (
        researches,
        research_index,
        research_path,
    ) = (
        load_canonical_research(
            case_id
        )
    )

    researches_by_issue = {}

    for research in researches:

        researches_by_issue.setdefault(
            research[
                "source_issue_id"
            ],
            [],
        ).append(
            research
        )

    timeline_context = (
        load_canonical_timeline(
            case_id
        )
    )

    event_index = timeline_context[
        "events"
    ]

    documents_index = (
        load_legal_documents_index()
    )

    warnings = []

    if not research_path.exists():

        warnings.append(
            "Canonical research.json bulunamadı; "
            "case-law intent'leri yalnız topic-based "
            "fallback ile kurulacaktır."
        )

    def build_intent_fn(
        issue,
    ):

        return (
            build_case_law_intent(
                issue,
                researches_by_issue.get(
                    issue[
                        "issue_id"
                    ],
                    [],
                ),
                event_index,
            )
        )

    # ========================================================
    # DETERMINISTIC COVERAGE + DECISIONS (HER ISSUE İÇİN -
    # source of truth)
    # ========================================================

    (
        raw_coverage,
        raw_decisions,
        discovery_warnings,
    ) = (
        run_case_law_discovery_for_issues(
            issues=
                issues,

            build_intent_fn=
                build_intent_fn,

            documents_index=
                documents_index,

            retrieval_fn=
                retrieval_fn,

            network_allowed=
                network_allowed,
        )
    )

    warnings.extend(
        discovery_warnings
    )

    coverage_records = (
        finalize_coverage(
            raw_coverage
        )
    )

    decision_records = (
        finalize_decisions(
            raw_decisions
        )
    )

    # ========================================================
    # OPTIONAL AGENT LAYER (LLM, EK AGENT SUGGESTION)
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

    suggestion_records = []

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

                research_index=
                    research_index,

                start_index=
                    1,

                existing_titles=[
                    coverage[
                        "title"
                    ]
                    for coverage
                    in coverage_records
                ],

                llm_client=
                    llm_client,

                network_allowed=
                    network_allowed,
            )
        )

        suggestion_records = (
            agent_candidates
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
            2,

        "case_law_analysis_id":
            f"case_law_{case_id}_v1",

        "case_id":
            case_id,

        "status":
            status,

        "generated_at":
            datetime.now()
            .astimezone()
            .isoformat(),

        "case_law_coverage":
            coverage_records,

        "case_law_decisions":
            decision_records,

        "case_law_agent_suggestions":
            suggestion_records,

        "warnings":
            warnings,

        "notes":
            (
                "Case Law Engine V2 çekirdeği (deterministik "
                "Case Law Policy + Case Law Discovery: "
                "query_parser + retriever, canonical "
                "documents.json ile çift doğrulama) "
                "canonical issues.json içindeki HER issue "
                "için tam olarak bir coverage kaydı ve o "
                "issue'ya bağlı 0..N grounded decision kaydı "
                "üretir; source of truth / safety "
                "boundary'dir. Retrieval sıralaması hiçbir "
                "hukuki üstünlük/emsal gücü ifade etmez. "
                + (
                    "Bu çalıştırmada Case Law Agent V1 "
                    "(LLM) da etkinleştirilmiştir; agent "
                    "yalnız case_law_agent_suggestions "
                    "dizisine EK kayıt ekleyebilir, court "
                    "metadata'ya ASLA karışamaz (şema "
                    "düzeyinde bu alanlar bu tipte "
                    "tanımlı değildir). "
                    if use_agent
                    else "Bu çalıştırmada Case Law Agent "
                    "(LLM) devre dışıdır. "
                )
                + "Hiçbir decision, bir mahkeme kararının "
                "uyuşmazlığa uygulanabilir olduğunu veya "
                "case outcome'u kesinleştirmez."
            ),
    }

    validate_engine_output_semantics(
        analysis,
        expected_issue_count=
            len(
                issue_index
            ),
    )

    return {
        "analysis":
            analysis,

        "issue_count":
            len(
                issue_index
            ),

        "research_count":
            len(
                research_index
            ),

        "document_count":
            len(
                documents_index
            ),

        "coverage_count":
            len(
                coverage_records
            ),

        "decision_count":
            len(
                decision_records
            ),

        "agent_suggestion_count":
            len(
                suggestion_records
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
    expected_issue_count,
):

    case_law_dir = (
        get_case_law_dir(
            case_id
        )
    )

    case_law_dir.mkdir(
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
            validate_case_law_analysis(
                case_law_path=
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

            raise CaseLawEngineError(
                "Post-write Case Law Validator "
                "valid=False."
            )

        written = load_json(
            pending_path
        )

        validate_engine_output_semantics(
            written,
            expected_issue_count,
        )

        if (
            canonical_exists_before
            != canonical_path.exists()
        ):

            raise CaseLawEngineError(
                "Case Law Engine canonical case_law.json "
                "durumunu değiştirdi."
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
        build_case_law_engine_output(
            case_id,
            use_agent=
                use_agent,

            llm_client=
                llm_client,

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
        build_result[
            "issue_count"
        ],
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

        "research_count":
            build_result[
                "research_count"
            ],

        "document_count":
            build_result[
                "document_count"
            ],

        "coverage_count":
            build_result[
                "coverage_count"
            ],

        "decision_count":
            build_result[
                "decision_count"
            ],

        "agent_suggestion_count":
            build_result[
                "agent_suggestion_count"
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
            "Vergi AI Case Law Engine V2"
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
            "Case Law Agent V1 (LLM) katmanını da çalıştır. "
            "Tek başına GERÇEK NETWORK ÇAĞRISI YAPMAZ; "
            "ayrıca --allow-network gerekir."
        ),
    )

    parser.add_argument(
        "--allow-network",
        action="store_true",
        dest="allow_network",
        help=(
            "İKİNCİ AÇIK GATE: hiçbir gerçek Anthropic/"
            "OpenAI API çağrısı bu bayrak olmadan "
            "yapılmaz."
        ),
    )

    args = parser.parse_args()

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - CASE LAW ENGINE V2"
    )

    print(
        "======================================"
    )

    print()

    print(
        "Case-law coverage/decision üretiliyor..."
    )

    print(
        "Engine:",
        CASE_LAW_ENGINE_VERSION,
    )

    print(
        "Policy:",
        CASE_LAW_POLICY_VERSION,
    )

    print(
        "Discovery:",
        CASE_LAW_DISCOVERY_VERSION,
        (
            "(network açık)"
            if args.allow_network
            else "(network KAPALI - retrieval_not_run "
            "üretilecek)"
        ),
    )

    if args.with_agent and args.allow_network:

        agent_status = (
            CASE_LAW_AGENT_VERSION
            + " (network açık - gerçek API çağrısı "
            "denenebilir)"
        )

    elif args.with_agent:

        agent_status = (
            CASE_LAW_AGENT_VERSION
            + " (network KAPALI - --allow-network "
            "verilmedi; agent atlanacak)"
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

                use_agent=
                    args.with_agent,

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
            " CASE LAW ENGINE V2: FAIL"
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
        "CASE LAW ANALYSIS OLUŞTURULDU"
    )

    print(
        "Analysis ID:",
        analysis[
            "case_law_analysis_id"
        ],
    )

    print(
        "Canonical issue:",
        result[
            "issue_count"
        ],
    )

    print(
        "Canonical research:",
        result[
            "research_count"
        ],
    )

    print(
        "Canonical documents:",
        result[
            "document_count"
        ],
    )

    print(
        "Coverage count (1 per issue):",
        result[
            "coverage_count"
        ],
    )

    print(
        "Decision count (0..N per issue):",
        result[
            "decision_count"
        ],
    )

    print(
        "Agent suggestion count:",
        result[
            "agent_suggestion_count"
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

    for coverage in analysis[
        "case_law_coverage"
    ]:

        print(
            "-",
            coverage[
                "coverage_id"
            ],
            "|",
            "issue=" + coverage[
                "source_issue_id"
            ],
            "|",
            coverage[
                "execution_state"
            ],
            "|",
            "decisions=" + str(
                coverage[
                    "decision_count"
                ]
            ),
        )

        print(
            "  ",
            coverage[
                "title"
            ],
        )

    if analysis[
        "case_law_decisions"
    ]:

        print()

        print(
            "Decisions:"
        )

        for decision in analysis[
            "case_law_decisions"
        ]:

            print(
                "-",
                decision[
                    "decision_id"
                ],
                "|",
                "issue=" + decision[
                    "source_issue_id"
                ],
                "|",
                decision[
                    "source_document_id"
                ],
                "|",
                decision[
                    "court_name"
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
        "- court_name/court_unit/case_number/"
        "decision_number/decision_date/source_url "
        "yalnız canonical documents.json (belge_turu="
        "'Yargı Kararı') ile birebir doğrulanmış "
        "kayıttan gelebilir."
    )

    print(
        "- LLM (Agent):",
        agent_status,
    )

    print(
        "- Agent court metadata dolduramaz (şema "
        "düzeyinde bu alanlar agent_suggestion tipinde "
        "tanımlı değildir)."
    )

    print(
        "- Her canonical issue tam olarak bir coverage "
        "kaydı aldı (sessiz coverage boşluğu yok)."
    )

    print(
        "- Aynı source_document_id aynı issue altında "
        "duplicate üretilemez."
    )

    print(
        "- Retrieval sıralaması hukuki üstünlük ifade "
        "etmez."
    )

    print(
        "- Case outcome / kesin hukuki sonuç ifadesi "
        "üretilmemiştir."
    )

    print(
        "- Canonical case_law.json değiştirilmemiştir."
    )

    print()

    print(
        "======================================"
    )

    print(
        " CASE LAW ENGINE V2: PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    main()
