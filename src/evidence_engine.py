# ============================================================
# VERGİ AI - EVIDENCE ENGINE V1
#
# AMAÇ
# ----
#
# Canonical issues.json (Row 9) + approved canonical
# facts.json (Row 6) + active canonical case document.json
# (Row 3) üzerinden Evidence Discovery V1'i (deterministik
# allowlist) ve (opsiyonel) Evidence Agent V1'i (LLM seçimi)
# çalıştırıp sonucu:
#
#     data/cases/<case_id>/evidence/
#     evidence_<case_id>_v1.json.pending
#
# olarak üretmek.
#
#
# KRİTİK GÜVENLİK
# ----------------
#
# - Engine canonical evidence.json dosyasına YAZMAZ.
# - HER canonical issue için TAM OLARAK BİR coverage kaydı
#   üretilir - sessiz coverage boşluğu ENGELLENİR.
# - Agent (evidence_agent.py, LLM) VARSAYILAN OLARAK
#   KAPALIDIR; açıldığında yalnız evidence_candidates ve
#   evidence_agent_suggestions dizilerine kayıt ekler.
# - Gerçek network çağrısı (LLM) için --allow-network şarttır;
#   --with-agent tek başına yetmez.
# - Bu Row'da RETRIEVAL/AĞ bağımlılığı YOKTUR - allowlist
#   tamamen canonical veri üzerinde yerel bir küme işlemidir.
#   execution_state yalnız Agent'ın çalışıp çalışmadığına ve
#   cevabının şekil/grounding açısından geçerliliğine bağlıdır.
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


from legal_research_validator import (
    load_canonical_issues,
)

from timeline_validator import (
    load_canonical_fact_index,
)

from issue_spotting_validator import (
    FORBIDDEN_PHRASES,
)

from timeline_consolidation_policy import (
    normalize_text_tr,
)

from evidence_policy import (
    EVIDENCE_POLICY_VERSION,
    ZERO_CANDIDATE_EXECUTION_STATES,
    ZERO_SUGGESTION_EXECUTION_STATES,
    finalize_coverage,
    load_active_case_documents_index,
    sha256_of,
)

from evidence_discovery import (
    EVIDENCE_DISCOVERY_VERSION,
    build_allowlist_for_issues,
    build_coverage_record,
)

from evidence_agent import (
    EVIDENCE_AGENT_VERSION,
    generate_agent_output,
)

from evidence_validator import (
    validate_evidence_analysis,
)


# ============================================================
# VERSION
# ============================================================

EVIDENCE_ENGINE_VERSION = "1"

ALL_FORBIDDEN_PHRASES = tuple(
    FORBIDDEN_PHRASES
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

class EvidenceEngineError(
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

def get_evidence_dir(
    case_id,
):

    return (
        CASES_DIR
        / case_id
        / "evidence"
    )


def get_pending_path(
    case_id,
):

    return (
        get_evidence_dir(
            case_id
        )
        / (
            f"evidence_{case_id}_v1.json.pending"
        )
    )


def get_canonical_path(
    case_id,
):

    return (
        get_evidence_dir(
            case_id
        )
        / "evidence.json"
    )


def get_history_dir(
    case_id,
):

    return (
        get_evidence_dir(
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
            "evidence_pending_before_engine_"
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
    *texts,
):

    combined = normalize_text_tr(
        " ".join(
            text or ""
            for text in texts
        )
    )

    for phrase in ALL_FORBIDDEN_PHRASES:

        if phrase in combined:

            raise EvidenceEngineError(
                "Kayıt kesin hukuki sonuç/admissibility "
                f"ifadesi içeriyor ('{phrase}'): {record_id}"
            )


def validate_engine_output_semantics(
    analysis,
    expected_issue_count,
):

    if not isinstance(
        analysis,
        dict,
    ):

        raise EvidenceEngineError(
            "Evidence analysis dict değil."
        )

    coverage_records = analysis.get(
        "evidence_coverage"
    )

    candidate_records = analysis.get(
        "evidence_candidates"
    )

    suggestion_records = analysis.get(
        "evidence_agent_suggestions"
    )

    if not isinstance(
        coverage_records,
        list,
    ) or not isinstance(
        candidate_records,
        list,
    ) or not isinstance(
        suggestion_records,
        list,
    ):

        raise EvidenceEngineError(
            "evidence_coverage/evidence_candidates/"
            "evidence_agent_suggestions alanlarından biri "
            "list değil."
        )

    covered_issue_ids = set()

    for coverage in coverage_records:

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

            raise EvidenceEngineError(
                "Coverage kaydı status/requires_human_review "
                f"kısıtını ihlal ediyor: "
                f"{coverage.get('coverage_id')}"
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
            coverage.get(
                "execution_state"
            )
            in ZERO_CANDIDATE_EXECUTION_STATES
            and coverage.get(
                "candidate_count"
            )
            != 0
        ):

            raise EvidenceEngineError(
                "Coverage execution_state="
                f"{coverage.get('execution_state')} iken "
                "candidate_count 0 olmalıdır: "
                f"{coverage.get('coverage_id')}"
            )

        if (
            coverage.get(
                "execution_state"
            )
            in ZERO_SUGGESTION_EXECUTION_STATES
            and coverage.get(
                "suggestion_count"
            )
            != 0
        ):

            raise EvidenceEngineError(
                "Coverage execution_state="
                f"{coverage.get('execution_state')} iken "
                "suggestion_count 0 olmalıdır: "
                f"{coverage.get('coverage_id')}"
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

        raise EvidenceEngineError(
            "Her canonical issue tam olarak bir coverage "
            f"kaydı almalıdır. Beklenen="
            f"{expected_issue_count}, "
            f"Bulunan (benzersiz issue)="
            f"{len(covered_issue_ids)}, "
            f"Bulunan (toplam kayıt)="
            f"{len(coverage_records)}"
        )

    seen_dedup_keys = set()

    for candidate in candidate_records:

        if (
            candidate.get(
                "status"
            )
            != "candidate"
            or candidate.get(
                "requires_human_review"
            )
            is not True
        ):

            raise EvidenceEngineError(
                "Candidate kaydı status/requires_human_review "
                f"kısıtını ihlal ediyor: "
                f"{candidate.get('candidate_id')}"
            )

        if (
            candidate.get(
                "review_state"
            )
            != "needs_review"
        ):

            raise EvidenceEngineError(
                "Engine çıktısında review_state yalnız "
                "'needs_review' olabilir: "
                f"{candidate.get('candidate_id')}"
            )

        dedup_key = (
            candidate.get(
                "source_issue_id"
            ),

            candidate.get(
                "source_fact_id"
            ),

            candidate.get(
                "source_document_id"
            ),

            candidate.get(
                "relationship_candidate"
            ),
        )

        if dedup_key in seen_dedup_keys:

            raise EvidenceEngineError(
                "Aynı (issue, fact, document, relationship) "
                f"DUPLICATE üretildi: {dedup_key}"
            )

        seen_dedup_keys.add(
            dedup_key
        )

        for forbidden_field in (
            "confidence",
            "evidence_strength",
            "priority",
            "admissibility",
        ):

            if forbidden_field in candidate:

                raise EvidenceEngineError(
                    "Candidate kaydı yapısal olarak "
                    f"yasak bir alan taşıyor "
                    f"('{forbidden_field}'): "
                    f"{candidate.get('candidate_id')}"
                )

        check_forbidden_phrases(
            candidate.get(
                "candidate_id"
            ),

            candidate.get(
                "grounded_explanation"
            ),
        )

    for suggestion in suggestion_records:

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

            raise EvidenceEngineError(
                "Suggestion kaydı status/requires_human_review "
                f"kısıtını ihlal ediyor: "
                f"{suggestion.get('suggestion_id')}"
            )

        if (
            suggestion.get(
                "suggestion_review_state"
            )
            != "needs_review"
        ):

            raise EvidenceEngineError(
                "Engine çıktısında suggestion_review_state "
                "yalnız 'needs_review' olabilir: "
                f"{suggestion.get('suggestion_id')}"
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

def build_evidence_engine_output(
    case_id,
    use_agent=False,
    llm_client=None,
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

    fact_context = (
        load_canonical_fact_index(
            case_id
        )
    )

    fact_index = {
        fact_id: record
        for fact_id, record
        in fact_context[
            "facts"
        ].items()
    }

    active_documents_index = (
        load_active_case_documents_index(
            case_id
        )
    )

    warnings = []

    (
        allowlist_by_issue,
        discovery_warnings,
    ) = build_allowlist_for_issues(
        issues,
        fact_index,
        active_documents_index,
    )

    warnings.extend(
        discovery_warnings
    )

    # ========================================================
    # OPTIONAL AGENT LAYER (LLM)
    # ========================================================

    agent_result = {
        "candidates": [],
        "suggestions": [],
        "warnings": [],
        "call_failed": False,
        "unparseable": False,
        "per_issue": {},
    }

    agent_enabled = bool(
        use_agent
    )

    if agent_enabled:

        agent_result = (
            generate_agent_output(
                case_id=
                    case_id,

                issue_index=
                    issue_index,

                allowlist_by_issue=
                    allowlist_by_issue,

                fact_index=
                    fact_index,

                active_documents_index=
                    active_documents_index,

                candidate_start_index=
                    1,

                suggestion_start_index=
                    1,

                llm_client=
                    llm_client,

                network_allowed=
                    network_allowed,
            )
        )

        warnings.extend(
            agent_result[
                "warnings"
            ]
        )

    candidate_records = agent_result[
        "candidates"
    ]

    suggestion_records = agent_result[
        "suggestions"
    ]

    candidates_by_issue = {}

    for candidate in candidate_records:

        candidates_by_issue.setdefault(
            candidate[
                "source_issue_id"
            ],
            0,
        )

        candidates_by_issue[
            candidate[
                "source_issue_id"
            ]
        ] += 1

    suggestions_by_issue = {}

    for suggestion in suggestion_records:

        suggestions_by_issue.setdefault(
            suggestion[
                "source_issue_id"
            ],
            0,
        )

        suggestions_by_issue[
            suggestion[
                "source_issue_id"
            ]
        ] += 1

    # ========================================================
    # COVERAGE (HER ISSUE İÇİN - source of truth)
    # ========================================================

    raw_coverage = []

    for issue in issues:

        issue_id = issue[
            "issue_id"
        ]

        entries = allowlist_by_issue.get(
            issue_id,
            [],
        )

        allowlist_count = len(
            entries
        )

        candidate_count = candidates_by_issue.get(
            issue_id,
            0,
        )

        suggestion_count = suggestions_by_issue.get(
            issue_id,
            0,
        )

        if allowlist_count == 0:

            execution_state = (
                "blocked_missing_input"
            )

            reason_codes = [
                "no_resolvable_approved_fact_or_"
                "active_document"
            ]

        elif not agent_enabled:

            execution_state = (
                "analysis_not_run"
            )

            reason_codes = []

        elif agent_result[
            "call_failed"
        ]:

            execution_state = (
                "analysis_failed"
            )

            reason_codes = [
                "agent_call_failed"
            ]

        elif agent_result[
            "unparseable"
        ]:

            execution_state = (
                "analysis_failed"
            )

            reason_codes = [
                "agent_response_unparseable"
            ]

        else:

            bucket = agent_result[
                "per_issue"
            ].get(
                issue_id,
                {},
            )

            reason_codes = []

            if bucket.get(
                "rejected_candidate_count",
                0,
            ) > 0:

                reason_codes.append(
                    "candidate_rejected_shape_or_"
                    "grounding_invalid"
                )

            if bucket.get(
                "rejected_suggestion_count",
                0,
            ) > 0:

                reason_codes.append(
                    "suggestion_rejected_shape_or_"
                    "grounding_invalid"
                )

            execution_state = (
                "analysis_partial"
                if reason_codes
                else "analysis_completed"
            )

        raw_coverage.append(
            build_coverage_record(
                issue,
                execution_state,
                allowlist_count,
                candidate_count=
                    candidate_count,

                suggestion_count=
                    suggestion_count,

                reason_codes=
                    reason_codes,
            )
        )

    coverage_records = (
        finalize_coverage(
            raw_coverage
        )
    )

    # ========================================================
    # ANALYSIS METADATA (INPUT MANIFEST / STALE GUARD)
    # ========================================================

    analysis_metadata = {
        "issues_input_hash":
            sha256_of(
                issues
            ),

        "facts_input_hash":
            sha256_of(
                {
                    fact_id: record[
                        "fact"
                    ]
                    for fact_id, record
                    in fact_index.items()
                }
            ),

        "documents_input_hash":
            sha256_of(
                active_documents_index
            ),
    }

    status = (
        "completed"
        if issues
        else "failed"
    )

    analysis = {
        "schema_version":
            1,

        "evidence_analysis_id":
            f"evidence_{case_id}_v1",

        "case_id":
            case_id,

        "status":
            status,

        "generated_at":
            datetime.now()
            .astimezone()
            .isoformat(),

        "analysis_metadata":
            analysis_metadata,

        "evidence_coverage":
            coverage_records,

        "evidence_candidates":
            candidate_records,

        "evidence_agent_suggestions":
            suggestion_records,

        "warnings":
            warnings,

        "notes":
            (
                "Evidence Engine V1 çekirdeği (deterministik "
                "Evidence Discovery: yalnız approved fact + "
                "active canonical case document) canonical "
                "issues.json içindeki HER issue için tam "
                "olarak bir coverage kaydı üretir; source of "
                "truth / safety boundary'dir. "
                + (
                    "Bu çalıştırmada Evidence Agent V1 (LLM) "
                    "da etkinleştirilmiştir; agent yalnız "
                    "deterministik allowlist içinden "
                    "supports/contradicts seçimi yapabilir ve "
                    "izin verilen suggestion türlerini "
                    "önerebilir. "
                    if agent_enabled
                    else "Bu çalıştırmada Evidence Agent "
                    "(LLM) devre dışıdır. "
                )
                + "Hiçbir candidate, fact'in kendi doğruluğunu "
                "yeniden değerlendirmez, admissibility/"
                "strength/sufficiency veya davanın kazanılma "
                "ihtimalini ifade etmez."
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

        "fact_count":
            len(
                fact_index
            ),

        "active_document_count":
            len(
                active_documents_index
            ),

        "coverage_count":
            len(
                coverage_records
            ),

        "candidate_count":
            len(
                candidate_records
            ),

        "suggestion_count":
            len(
                suggestion_records
            ),

        "agent_enabled":
            agent_enabled,
    }


# ============================================================
# WRITE PENDING
# ============================================================

def write_pending(
    case_id,
    analysis,
    expected_issue_count,
):

    evidence_dir = (
        get_evidence_dir(
            case_id
        )
    )

    evidence_dir.mkdir(
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
            validate_evidence_analysis(
                evidence_path=
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

            raise EvidenceEngineError(
                "Post-write Evidence Validator valid=False."
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

            raise EvidenceEngineError(
                "Evidence Engine canonical evidence.json "
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
        build_evidence_engine_output(
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
        build_result[
            "issue_count"
        ],
    )

    result = dict(
        build_result
    )

    result[
        "pending_path"
    ] = pending_path

    result[
        "validation"
    ] = validation

    result[
        "previous_pending_history"
    ] = previous_pending_history

    return result


# ============================================================
# SELF TEST (ENGINE-LEVEL SEMANTIC GUARD)
#
# Row 9-11 geleneğinde engine kendi kendine bir --self-test
# sunmaz; ancak kullanıcı Row 12 test planında açıkça
# "Agent confirmed/rejected rejection" testini istediği ve bu
# kontrol yalnız evidence_engine.py'de yaşadığı için, burada
# hedefli bir self-test eklenmiştir.
# ============================================================

def run_self_test(
    case_id="case_0001",
):

    from evidence_agent import (
        FakeEvidenceLLMClient,
    )

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - EVIDENCE ENGINE V1"
    )

    print(
        "======================================"
    )

    # ========================================================
    # T01 OFFLINE END-TO-END BASELINE
    # ========================================================

    offline_result = (
        build_evidence_engine_output(
            case_id,

            use_agent=
                False,
        )
    )

    assert (
        offline_result[
            "coverage_count"
        ]
        == offline_result[
            "issue_count"
        ]
    )

    assert offline_result[
        "candidate_count"
    ] == 0

    assert offline_result[
        "suggestion_count"
    ] == 0

    assert all(
        coverage[
            "execution_state"
        ]
        in (
            "analysis_not_run",
            "blocked_missing_input",
        )
        for coverage in offline_result[
            "analysis"
        ][
            "evidence_coverage"
        ]
    )

    print(
        "T01 Offline end-to-end baseline (coverage "
        "completeness, 0 candidate/suggestion):",
        "PASS"
    )

    # ========================================================
    # T02 END-TO-END WITH AGENT PRODUCING ONE CANDIDATE
    # ========================================================

    from evidence_discovery import (
        build_allowlist_for_issues,
    )

    from legal_research_validator import (
        load_canonical_issues,
    )

    from timeline_validator import (
        load_canonical_fact_index,
    )

    issue_context = (
        load_canonical_issues(
            case_id
        )
    )

    fact_context = (
        load_canonical_fact_index(
            case_id
        )
    )

    active_documents_index = (
        load_active_case_documents_index(
            case_id
        )
    )

    (
        allowlist_by_issue,
        _warnings,
    ) = build_allowlist_for_issues(
        issue_context[
            "issues"
        ],

        fact_context[
            "facts"
        ],

        active_documents_index,
    )

    entry = next(
        entries[
            0
        ]
        for entries
        in allowlist_by_issue.values()
        if entries
    )

    good_response = json.dumps(
        {
            "candidates": [
                {
                    "source_issue_id":
                        entry[
                            "issue_id"
                        ],

                    "source_fact_id":
                        entry[
                            "fact_id"
                        ],

                    "source_document_id":
                        entry[
                            "document_id"
                        ],

                    "relationship_candidate":
                        "supports",

                    "reason_code":
                        "explicit_textual_match",
                },
            ],

            "suggestions": [],
        },
        ensure_ascii=False,
    )

    client = FakeEvidenceLLMClient(
        response_text=
            good_response
    )

    agent_result = (
        build_evidence_engine_output(
            case_id,

            use_agent=
                True,

            llm_client=
                client,
        )
    )

    assert agent_result[
        "candidate_count"
    ] == 1

    matching_coverage = next(
        coverage
        for coverage in agent_result[
            "analysis"
        ][
            "evidence_coverage"
        ]
        if coverage[
            "source_issue_id"
        ]
        == entry[
            "issue_id"
        ]
    )

    assert matching_coverage[
        "execution_state"
    ] == "analysis_completed"

    assert matching_coverage[
        "candidate_count"
    ] == 1

    print(
        "T02 End-to-end run with agent producing one "
        "grounded candidate (analysis_completed):",
        "PASS"
    )

    # ========================================================
    # T03 AGENT CONFIRMED/REJECTED REJECTION (ENGINE OUTPUT
    # MAY NEVER CONTAIN A NON-'needs_review' REVIEW STATE)
    # ========================================================

    tampered = json.loads(
        json.dumps(
            agent_result[
                "analysis"
            ]
        )
    )

    tampered[
        "evidence_candidates"
    ][
        0
    ][
        "review_state"
    ] = "confirmed"

    raised = False

    try:

        validate_engine_output_semantics(
            tampered,
            agent_result[
                "issue_count"
            ],
        )

    except EvidenceEngineError:

        raised = True

    assert raised is True, (
        "Engine, review_state='confirmed' taşıyan bir "
        "çıktıyı kabul etmemelidir (bu yalnız Layer B "
        "human review ile mümkündür)."
    )

    print(
        "T03 Engine output with review_state='confirmed' "
        "rejected (Agent can only ever produce "
        "'needs_review'):",
        "PASS"
    )

    # ========================================================
    # T04 DUPLICATE DEDUP KEY REJECTED AT ENGINE-SEMANTIC
    # GUARD LEVEL
    # ========================================================

    tampered = json.loads(
        json.dumps(
            agent_result[
                "analysis"
            ]
        )
    )

    duplicate_candidate = json.loads(
        json.dumps(
            tampered[
                "evidence_candidates"
            ][
                0
            ]
        )
    )

    duplicate_candidate[
        "candidate_id"
    ] = "evidence_candidate_999"

    tampered[
        "evidence_candidates"
    ].append(
        duplicate_candidate
    )

    raised = False

    try:

        validate_engine_output_semantics(
            tampered,
            agent_result[
                "issue_count"
            ],
        )

    except EvidenceEngineError:

        raised = True

    assert raised is True

    print(
        "T04 Duplicate (issue, fact, document, "
        "relationship) rejected at engine-semantic-guard "
        "level:",
        "PASS"
    )

    print()

    print(
        "======================================"
    )

    print(
        " EVIDENCE ENGINE V1: 4/4 PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Vergi AI Evidence Engine V1"
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
            "Evidence Agent V1 (LLM) katmanını da çalıştır. "
            "Tek başına GERÇEK NETWORK ÇAĞRISI YAPMAZ; ayrıca "
            "--allow-network gerekir."
        ),
    )

    parser.add_argument(
        "--allow-network",
        action="store_true",
        dest="allow_network",
        help=(
            "İKİNCİ AÇIK GATE: hiçbir gerçek Anthropic API "
            "çağrısı bu bayrak olmadan yapılmaz."
        ),
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
        dest="self_test",
        help=(
            "Engine-level semantic guard self-test'ini "
            "çalıştır (pending dosyası YAZMAZ)."
        ),
    )

    args = parser.parse_args()

    if args.self_test:

        run_self_test(
            args.case_id
        )

        return

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - EVIDENCE ENGINE V1"
    )

    print(
        "======================================"
    )

    print()

    print(
        "Evidence coverage/candidate üretiliyor..."
    )

    print(
        "Engine:",
        EVIDENCE_ENGINE_VERSION,
    )

    print(
        "Policy:",
        EVIDENCE_POLICY_VERSION,
    )

    print(
        "Discovery:",
        EVIDENCE_DISCOVERY_VERSION,
    )

    if args.with_agent and args.allow_network:

        agent_status = (
            EVIDENCE_AGENT_VERSION
            + " (network açık - gerçek API çağrısı "
            "denenebilir)"
        )

    elif args.with_agent:

        agent_status = (
            EVIDENCE_AGENT_VERSION
            + " (network KAPALI - --allow-network "
            "verilmedi; agent atlanacak, allowlist>=1 "
            "issue'lar analysis_not_run kalacak)"
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
            " EVIDENCE ENGINE V1: FAIL"
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
        "EVIDENCE ANALYSIS OLUŞTURULDU"
    )

    print(
        "Analysis ID:",
        analysis[
            "evidence_analysis_id"
        ],
    )

    print(
        "Canonical issue:",
        result[
            "issue_count"
        ],
    )

    print(
        "Approved fact:",
        result[
            "fact_count"
        ],
    )

    print(
        "Active canonical document:",
        result[
            "active_document_count"
        ],
    )

    print(
        "Coverage count (1 per issue):",
        result[
            "coverage_count"
        ],
    )

    print(
        "Candidate count:",
        result[
            "candidate_count"
        ],
    )

    print(
        "Suggestion count:",
        result[
            "suggestion_count"
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
        "evidence_coverage"
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
            "allowlist=" + str(
                coverage[
                    "allowlist_count"
                ]
            ),
            "|",
            "candidates=" + str(
                coverage[
                    "candidate_count"
                ]
            ),
            "|",
            "suggestions=" + str(
                coverage[
                    "suggestion_count"
                ]
            ),
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
        "- Yalnız approved (canonical) fact + active "
        "canonical case document ikilileri allowlist'e "
        "alındı."
    )

    print(
        "- LLM (Agent):",
        agent_status,
    )

    print(
        "- Agent yalnız deterministik allowlist içinden "
        "seçim yapabildi; confidence/strength/admissibility "
        "alanı yapısal olarak tanımlı değildir."
    )

    print(
        "- Her canonical issue tam olarak bir coverage "
        "kaydı aldı (sessiz coverage boşluğu yok)."
    )

    print(
        "- review_state/suggestion_review_state yalnız "
        "'needs_review' olarak üretildi."
    )

    print(
        "- Canonical evidence.json değiştirilmemiştir."
    )

    print()

    print(
        "======================================"
    )

    print(
        " EVIDENCE ENGINE V1: PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    main()
