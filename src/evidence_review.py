# ============================================================
# VERGİ AI - EVIDENCE REVIEW V1 (LAYER B)
#
# AMAÇ
# ----
#
# Layer A (evidence_approval.py) ile CANONICAL hale gelmiş
# `evidence.json` içindeki BİREYSEL candidate/suggestion
# kayıtlarının review_state / suggestion_review_state alanını,
# avukat (human reviewer) tarafından açık bir mutation ile
# günceller.
#
#
# NEDEN AYRI BİR KATMAN (LAYER A'DAN FARKLI)
# --------------------------------------------
#
# Layer A yalnız PENDING ANALİZİ canonical hale getirir
# (pending -> canonical promosyonu, tüm review_state'ler hâlâ
# 'needs_review'dir). Layer B ise CANONICAL İÇİNDEKİ TEK BİR
# kaydın review_state'ini değiştirir - bu Rows 9-11'in hiçbirinde
# bulunmayan, Row 12 contract'ının açıkça talep ettiği YENİ bir
# mutation türüdür.
#
#
# İZİN VERİLEN GEÇİŞLER
# ----------------------
#
# Candidate  (review_state):
#     needs_review -> confirmed
#     needs_review -> rejected
#
# Suggestion (suggestion_review_state):
#     needs_review -> accepted_for_follow_up
#     needs_review -> dismissed
#
# Başka HİÇBİR geçişe izin verilmez (ör. confirmed -> rejected,
# rejected -> confirmed, dismissed -> accepted_for_follow_up
# YASAKTIR - yalnız needs_review kaynak durumundan başlanabilir).
#
#
# KRİTİK SEMANTİK
# ----------------
#
# 'confirmed' yalnız ilişkinin avukat tarafından DOĞRULANDIĞINI
# gösterir; admissibility, strength veya sufficiency kararı
# DEĞİLDİR (bkz. CLAUDE.md §11, Prensip 7).
#
#
# GÜVENLİK
# --------
#
# - Varsayılan çalışma REVIEW/DRY-RUN'dır (yalnız mevcut
#   durumu raporlar).
# - Açık --confirm / --reject / --accept-follow-up / --dismiss
#   flag'i olmadan MUTATION YAPILMAZ.
# - Her mutation:
#     - canonical dosyanın backup'ını alır,
#     - atomic write yapar,
#     - TAM dosyayı (schema + grounding + coverage +
#       dedup + stale-hash) evidence_validator ile
#       YENİDEN doğrular,
#     - pre/post SHA256 hesaplar,
#     - ayrı bir audit kaydı üretir
#       (reviews/evidence_reviews/ altında),
#     - herhangi bir adım başarısız olursa rollback yapar.
# - Yalnız 'needs_review' kaynak durumundan başlayan geçişlere
#   izin verilir; başka bir geçiş denemesi FAIL olur.
# ============================================================


import argparse
import hashlib
import json
import os
import shutil
import sys

from datetime import datetime
from pathlib import Path


from evidence_validator import (
    validate_evidence_analysis,
)


# ============================================================
# VERSION
# ============================================================

EVIDENCE_REVIEW_VERSION = "1"

DEFAULT_CASE_ID = "case_0001"

CANDIDATE_ALLOWED_TARGETS = {
    "confirmed",
    "rejected",
}

SUGGESTION_ALLOWED_TARGETS = {
    "accepted_for_follow_up",
    "dismissed",
}


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


# ============================================================
# EXCEPTION
# ============================================================

class EvidenceReviewError(
    Exception
):
    pass


# ============================================================
# PATH HELPERS
# ============================================================

def get_evidence_dir(
    case_id,
):

    return (
        CASES_DIR
        / case_id
        / "evidence"
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


def get_evidence_review_audit_dir(
    case_id,
):

    return (
        get_evidence_dir(
            case_id
        )
        / "reviews"
        / "evidence_reviews"
    )


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
            f"Dosya bulunamadı:\n{path}"
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


def sha256_file(
    path,
):

    digest = hashlib.sha256()

    with open(
        path,
        "rb",
    ) as file:

        while True:

            chunk = file.read(
                1024 * 1024
            )

            if not chunk:

                break

            digest.update(
                chunk
            )

    return digest.hexdigest()


def now_iso():

    return (
        datetime.now()
        .astimezone()
        .isoformat()
    )


def now_stamp():

    return (
        datetime.now()
        .strftime(
            "%Y%m%d_%H%M%S"
        )
    )


# ============================================================
# BACKUP
# ============================================================

def backup_canonical(
    canonical_path,
    audit_dir,
):

    canonical_path = Path(
        canonical_path
    )

    audit_dir = Path(
        audit_dir
    )

    audit_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    backup_path = (
        audit_dir
        / (
            "evidence.json.before_review_"
            + now_stamp()
            + ".bak"
        )
    )

    shutil.copy2(
        canonical_path,
        backup_path,
    )

    return backup_path


# ============================================================
# FIND RECORD
# ============================================================

def find_candidate(
    analysis,
    candidate_id,
):

    for candidate in analysis.get(
        "evidence_candidates",
        [],
    ):

        if (
            candidate.get(
                "candidate_id"
            )
            == candidate_id
        ):

            return candidate

    return None


def find_suggestion(
    analysis,
    suggestion_id,
):

    for suggestion in analysis.get(
        "evidence_agent_suggestions",
        [],
    ):

        if (
            suggestion.get(
                "suggestion_id"
            )
            == suggestion_id
        ):

            return suggestion

    return None


# ============================================================
# AUDIT RECORD
# ============================================================

def write_review_audit(
    audit_dir,
    case_id,
    evidence_analysis_id,
    record_type,
    record_id,
    previous_state,
    new_state,
    reviewer_ref,
    review_note,
    pre_sha256,
    post_sha256,
    backup_path,
):

    audit_dir = Path(
        audit_dir
    )

    audit_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    audit_path = (
        audit_dir
        / (
            "evidence_review_"
            + record_id
            + "_"
            + now_stamp()
            + ".review_audit.json"
        )
    )

    audit = {
        "audit_type":
            "evidence_candidate_review"
            if record_type == "candidate"
            else "evidence_suggestion_review",

        "review_version":
            EVIDENCE_REVIEW_VERSION,

        "case_id":
            case_id,

        "evidence_analysis_id":
            evidence_analysis_id,

        "record_type":
            record_type,

        "record_id":
            record_id,

        "previous_state":
            previous_state,

        "new_state":
            new_state,

        "reviewer_ref":
            reviewer_ref,

        "reviewed_at":
            now_iso(),

        "review_note":
            review_note,

        "pre_sha256":
            pre_sha256,

        "post_sha256":
            post_sha256,

        "canonical_backup":
            str(
                backup_path
            ),

        "review_semantics":
            (
                "'confirmed', ilişkinin avukat tarafından "
                "doğrulandığını gösterir; admissibility, "
                "strength veya sufficiency kararı DEĞİLDİR. "
                "'rejected', ilişkinin avukat tarafından "
                "reddedildiğini gösterir. Suggestion review "
                "kararları (accepted_for_follow_up/dismissed) "
                "gerçek delil üretmez, yalnız takip "
                "işaretlemesidir."
            ),
    }

    atomic_write_json(
        audit_path,
        audit,
    )

    return audit_path


# ============================================================
# CORE TRANSITION
# ============================================================

def apply_review_transition(
    case_id,
    record_type,
    record_id,
    target_state,
    reviewer_ref,
    review_note,
    canonical_path=None,
    audit_dir=None,
):

    if record_type not in (
        "candidate",
        "suggestion",
    ):

        raise EvidenceReviewError(
            f"Geçersiz record_type: {record_type}"
        )

    if (
        record_type == "candidate"
        and target_state
        not in CANDIDATE_ALLOWED_TARGETS
    ):

        raise EvidenceReviewError(
            "Candidate için geçersiz hedef durum: "
            f"{target_state} (izin verilen: "
            f"{sorted(CANDIDATE_ALLOWED_TARGETS)})"
        )

    if (
        record_type == "suggestion"
        and target_state
        not in SUGGESTION_ALLOWED_TARGETS
    ):

        raise EvidenceReviewError(
            "Suggestion için geçersiz hedef durum: "
            f"{target_state} (izin verilen: "
            f"{sorted(SUGGESTION_ALLOWED_TARGETS)})"
        )

    canonical_path = Path(
        canonical_path
        if canonical_path is not None
        else get_canonical_path(
            case_id
        )
    )

    audit_dir = Path(
        audit_dir
        if audit_dir is not None
        else get_evidence_review_audit_dir(
            case_id
        )
    )

    if not canonical_path.exists():

        raise EvidenceReviewError(
            "Canonical evidence.json bulunamadı:\n"
            f"{canonical_path}"
        )

    pre_sha256 = sha256_file(
        canonical_path
    )

    analysis = load_json(
        canonical_path
    )

    if record_type == "candidate":

        record = find_candidate(
            analysis,
            record_id,
        )

        state_field = "review_state"

    else:

        record = find_suggestion(
            analysis,
            record_id,
        )

        state_field = (
            "suggestion_review_state"
        )

    if record is None:

        raise EvidenceReviewError(
            f"{record_type} bulunamadı: {record_id}"
        )

    previous_state = record.get(
        state_field
    )

    if previous_state != "needs_review":

        raise EvidenceReviewError(
            f"{record_type} '{record_id}' için geçiş "
            "yalnız 'needs_review' kaynak durumundan "
            f"başlayabilir (mevcut durum: "
            f"'{previous_state}'). confirmed/rejected/"
            "accepted_for_follow_up/dismissed durumundan "
            "başka bir duruma geçiş YASAKTIR."
        )

    backup_path = backup_canonical(
        canonical_path,
        audit_dir,
    )

    try:

        record[
            state_field
        ] = target_state

        atomic_write_json(
            canonical_path,
            analysis,
        )

        validation = (
            validate_evidence_analysis(
                evidence_path=
                    canonical_path,

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

            raise EvidenceReviewError(
                "Post-review Evidence Validator "
                "valid=False."
            )

        post_sha256 = sha256_file(
            canonical_path
        )

        audit_path = (
            write_review_audit(
                audit_dir=
                    audit_dir,

                case_id=
                    case_id,

                evidence_analysis_id=
                    analysis.get(
                        "evidence_analysis_id"
                    ),

                record_type=
                    record_type,

                record_id=
                    record_id,

                previous_state=
                    previous_state,

                new_state=
                    target_state,

                reviewer_ref=
                    reviewer_ref,

                review_note=
                    review_note,

                pre_sha256=
                    pre_sha256,

                post_sha256=
                    post_sha256,

                backup_path=
                    backup_path,
            )
        )

    except Exception:

        shutil.copy2(
            backup_path,
            canonical_path,
        )

        raise

    return {
        "canonical_path":
            canonical_path,

        "backup_path":
            backup_path,

        "audit_path":
            audit_path,

        "pre_sha256":
            pre_sha256,

        "post_sha256":
            post_sha256,

        "previous_state":
            previous_state,

        "new_state":
            target_state,

        "validation":
            validation,
    }


# ============================================================
# REVIEW / DRY-RUN REPORT
# ============================================================

def run_review_report(
    case_id,
):

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - EVIDENCE REVIEW V1 (LAYER B)"
    )

    print(
        " MODE: REVIEW/DRY-RUN"
    )

    print(
        "======================================"
    )

    canonical_path = (
        get_canonical_path(
            case_id
        )
    )

    if not canonical_path.exists():

        print()

        print(
            "Canonical evidence.json henüz mevcut değil:"
        )

        print(
            canonical_path
        )

        print()

        print(
            "Layer B yalnız Layer A ile promote edilmiş "
            "canonical veri üzerinde çalışabilir."
        )

        print()

        print(
            "======================================"
        )

        print(
            " EVIDENCE REVIEW V1: NOTHING TO REVIEW"
        )

        print(
            "======================================"
        )

        return

    analysis = load_json(
        canonical_path
    )

    print()

    print(
        "Case:",
        analysis.get(
            "case_id"
        ),
    )

    print(
        "Analysis ID:",
        analysis.get(
            "evidence_analysis_id"
        ),
    )

    print()

    print(
        "Candidates:"
    )

    for candidate in analysis.get(
        "evidence_candidates",
        [],
    ):

        print(
            "-",
            candidate[
                "candidate_id"
            ],
            "|",
            candidate[
                "relationship_candidate"
            ],
            "|",
            "review_state="
            + candidate[
                "review_state"
            ],
        )

    print()

    print(
        "Suggestions:"
    )

    for suggestion in analysis.get(
        "evidence_agent_suggestions",
        [],
    ):

        print(
            "-",
            suggestion[
                "suggestion_id"
            ],
            "|",
            suggestion[
                "suggestion_type"
            ],
            "|",
            "suggestion_review_state="
            + suggestion[
                "suggestion_review_state"
            ],
        )

    print()

    print(
        "MUTATION:"
    )

    print(
        "- yapılmadı (--confirm/--reject/"
        "--accept-follow-up/--dismiss verilmedi)"
    )

    print()

    print(
        "======================================"
    )

    print(
        " EVIDENCE REVIEW V1: READY"
    )

    print(
        "======================================"
    )


# ============================================================
# SELF TEST (TEMPFILE ISOLATION - CANONICAL case_0001/evidence/
# ASLA DOKUNULMAZ)
# ============================================================

def run_self_test():

    import tempfile

    from evidence_validator import (
        build_demo_evidence_analysis,
    )

    from evidence_agent import (
        FakeEvidenceLLMClient,
    )

    from evidence_discovery import (
        build_allowlist_for_issues,
    )

    from legal_research_validator import (
        load_canonical_issues,
    )

    from timeline_validator import (
        load_canonical_fact_index,
    )

    from evidence_policy import (
        load_active_case_documents_index,
    )

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - EVIDENCE REVIEW V1 (SELF-TEST)"
    )

    print(
        "======================================"
    )

    real_case_id = "case_0001"

    issue_context = (
        load_canonical_issues(
            real_case_id
        )
    )

    fact_context = (
        load_canonical_fact_index(
            real_case_id
        )
    )

    active_documents_index = (
        load_active_case_documents_index(
            real_case_id
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

    non_empty_issue_ids = [
        issue_id
        for issue_id, entries
        in allowlist_by_issue.items()
        if entries
    ]

    entry_a = allowlist_by_issue[
        non_empty_issue_ids[
            0
        ]
    ][
        0
    ]

    good_response = json.dumps(
        {
            "candidates": [
                {
                    "source_issue_id":
                        entry_a[
                            "issue_id"
                        ],

                    "source_fact_id":
                        entry_a[
                            "fact_id"
                        ],

                    "source_document_id":
                        entry_a[
                            "document_id"
                        ],

                    "relationship_candidate":
                        "supports",

                    "reason_code":
                        "explicit_textual_match",
                },
            ],

            "suggestions": [
                {
                    "source_issue_id":
                        entry_a[
                            "issue_id"
                        ],

                    "suggestion_type":
                        "additional_verification",

                    "source_fact_id":
                        entry_a[
                            "fact_id"
                        ],

                    "source_document_id":
                        None,

                    "related_reference_ids": [
                        entry_a[
                            "fact_id"
                        ]
                    ],
                },
            ],
        },
        ensure_ascii=False,
    )

    client = FakeEvidenceLLMClient(
        response_text=
            good_response
    )

    analysis = (
        build_demo_evidence_analysis(
            real_case_id,

            use_agent=
                True,

            llm_client=
                client,
        )
    )

    candidate_id = analysis[
        "evidence_candidates"
    ][
        0
    ][
        "candidate_id"
    ]

    suggestion_id = analysis[
        "evidence_agent_suggestions"
    ][
        0
    ][
        "suggestion_id"
    ]

    temp_dir = tempfile.TemporaryDirectory(
        prefix=
            "evidence_review_selftest_"
    )

    isolated_canonical_path = (
        Path(
            temp_dir.name
        )
        / "evidence.json"
    )

    isolated_audit_dir = (
        Path(
            temp_dir.name
        )
        / "reviews"
        / "evidence_reviews"
    )

    atomic_write_json(
        isolated_canonical_path,
        analysis,
    )

    # ========================================================
    # T01 CONFIRM CANDIDATE (needs_review -> confirmed)
    # ========================================================

    result = apply_review_transition(
        case_id=
            real_case_id,

        record_type=
            "candidate",

        record_id=
            candidate_id,

        target_state=
            "confirmed",

        reviewer_ref=
            "test_reviewer",

        review_note=
            "Self-test confirm.",

        canonical_path=
            isolated_canonical_path,

        audit_dir=
            isolated_audit_dir,
    )

    assert result[
        "previous_state"
    ] == "needs_review"

    assert result[
        "new_state"
    ] == "confirmed"

    assert (
        result[
            "pre_sha256"
        ]
        != result[
            "post_sha256"
        ]
    )

    assert result[
        "audit_path"
    ].exists()

    assert result[
        "validation"
    ][
        "valid"
    ] is True

    reloaded = load_json(
        isolated_canonical_path
    )

    assert (
        find_candidate(
            reloaded,
            candidate_id,
        )[
            "review_state"
        ]
        == "confirmed"
    )

    print(
        "T01 Candidate needs_review -> confirmed "
        "(audit + SHA256 change + re-validation PASS):",
        "PASS"
    )

    # ========================================================
    # T02 INVALID RE-TRANSITION (confirmed -> rejected
    # FORBIDDEN - source must be needs_review)
    # ========================================================

    raised = False

    try:

        apply_review_transition(
            case_id=
                real_case_id,

            record_type=
                "candidate",

            record_id=
                candidate_id,

            target_state=
                "rejected",

            reviewer_ref=
                "test_reviewer",

            review_note=
                "Should fail.",

            canonical_path=
                isolated_canonical_path,

            audit_dir=
                isolated_audit_dir,
        )

    except EvidenceReviewError:

        raised = True

    assert raised is True

    reloaded = load_json(
        isolated_canonical_path
    )

    assert (
        find_candidate(
            reloaded,
            candidate_id,
        )[
            "review_state"
        ]
        == "confirmed"
    ), "Reddedilen geçiş canonical durumu değiştirmemelidir."

    print(
        "T02 Re-transition from non-'needs_review' state "
        "rejected (confirmed -> rejected forbidden):",
        "PASS"
    )

    # ========================================================
    # T03 UNKNOWN RECORD ID REJECTED
    # ========================================================

    raised = False

    try:

        apply_review_transition(
            case_id=
                real_case_id,

            record_type=
                "candidate",

            record_id=
                "evidence_candidate_does_not_exist",

            target_state=
                "confirmed",

            reviewer_ref=
                "test_reviewer",

            review_note=
                "Should fail.",

            canonical_path=
                isolated_canonical_path,

            audit_dir=
                isolated_audit_dir,
        )

    except EvidenceReviewError:

        raised = True

    assert raised is True

    print(
        "T03 Unknown candidate_id rejected:",
        "PASS"
    )

    # ========================================================
    # T04 INVALID TARGET STATE FOR CANDIDATE REJECTED
    # (e.g. 'dismissed' is a suggestion-only state)
    # ========================================================

    raised = False

    try:

        apply_review_transition(
            case_id=
                real_case_id,

            record_type=
                "candidate",

            record_id=
                candidate_id,

            target_state=
                "dismissed",

            reviewer_ref=
                "test_reviewer",

            review_note=
                "Should fail.",

            canonical_path=
                isolated_canonical_path,

            audit_dir=
                isolated_audit_dir,
        )

    except EvidenceReviewError:

        raised = True

    assert raised is True

    print(
        "T04 Invalid target state for candidate type "
        "rejected:",
        "PASS"
    )

    # ========================================================
    # T05 ACCEPT-FOLLOW-UP SUGGESTION
    # (needs_review -> accepted_for_follow_up)
    # ========================================================

    result = apply_review_transition(
        case_id=
            real_case_id,

        record_type=
            "suggestion",

        record_id=
            suggestion_id,

        target_state=
            "accepted_for_follow_up",

        reviewer_ref=
            "test_reviewer",

        review_note=
            "Self-test accept-follow-up.",

        canonical_path=
            isolated_canonical_path,

        audit_dir=
            isolated_audit_dir,
    )

    assert result[
        "new_state"
    ] == "accepted_for_follow_up"

    reloaded = load_json(
        isolated_canonical_path
    )

    assert (
        find_suggestion(
            reloaded,
            suggestion_id,
        )[
            "suggestion_review_state"
        ]
        == "accepted_for_follow_up"
    )

    print(
        "T05 Suggestion needs_review -> "
        "accepted_for_follow_up:",
        "PASS"
    )

    # ========================================================
    # T06 REJECT CANDIDATE ON A FRESH SECOND CANDIDATE
    # (needs_review -> rejected)
    # ========================================================

    second_client = FakeEvidenceLLMClient(
        response_text=
            good_response
    )

    entry_b = allowlist_by_issue[
        non_empty_issue_ids[
            1
        ]
        if len(
            non_empty_issue_ids
        )
        > 1
        else non_empty_issue_ids[
            0
        ]
    ][
        0
    ]

    second_response = json.dumps(
        {
            "candidates": [
                {
                    "source_issue_id":
                        entry_b[
                            "issue_id"
                        ],

                    "source_fact_id":
                        entry_b[
                            "fact_id"
                        ],

                    "source_document_id":
                        entry_b[
                            "document_id"
                        ],

                    "relationship_candidate":
                        "contradicts",

                    "reason_code":
                        "temporal_consistency",
                },
            ],

            "suggestions": [],
        },
        ensure_ascii=False,
    )

    second_client = FakeEvidenceLLMClient(
        response_text=
            second_response
    )

    second_analysis = (
        build_demo_evidence_analysis(
            real_case_id,

            use_agent=
                True,

            llm_client=
                second_client,
        )
    )

    second_candidate_id = second_analysis[
        "evidence_candidates"
    ][
        0
    ][
        "candidate_id"
    ]

    second_canonical_path = (
        Path(
            temp_dir.name
        )
        / "evidence_second.json"
    )

    atomic_write_json(
        second_canonical_path,
        second_analysis,
    )

    result = apply_review_transition(
        case_id=
            real_case_id,

        record_type=
            "candidate",

        record_id=
            second_candidate_id,

        target_state=
            "rejected",

        reviewer_ref=
            "test_reviewer",

        review_note=
            "Self-test reject.",

        canonical_path=
            second_canonical_path,

        audit_dir=
            isolated_audit_dir,
    )

    assert result[
        "new_state"
    ] == "rejected"

    print(
        "T06 Candidate needs_review -> rejected:",
        "PASS"
    )

    # ========================================================
    # T07 AUDIT FILE FIELDS
    # ========================================================

    audit_content = load_json(
        result[
            "audit_path"
        ]
    )

    assert audit_content[
        "record_id"
    ] == second_candidate_id

    assert audit_content[
        "previous_state"
    ] == "needs_review"

    assert audit_content[
        "new_state"
    ] == "rejected"

    assert audit_content[
        "reviewer_ref"
    ] == "test_reviewer"

    assert (
        audit_content[
            "pre_sha256"
        ]
        != audit_content[
            "post_sha256"
        ]
    )

    print(
        "T07 Review audit record carries reviewer_ref/"
        "reviewed_at/previous_state/new_state/pre-post "
        "SHA256:",
        "PASS"
    )

    # ========================================================
    # T08 ROLLBACK ON POST-WRITE VALIDATION FAILURE
    # ========================================================

    third_canonical_path = (
        Path(
            temp_dir.name
        )
        / "evidence_third.json"
    )

    third_analysis = json.loads(
        json.dumps(
            analysis
        )
    )

    # Reset the candidate back to needs_review so the
    # transition is attemptable, then corrupt an UNRELATED
    # required field so post-write validation must fail and
    # trigger rollback.

    third_analysis[
        "evidence_candidates"
    ][
        0
    ][
        "review_state"
    ] = "needs_review"

    third_analysis[
        "analysis_metadata"
    ][
        "facts_input_hash"
    ] = "0" * 64

    atomic_write_json(
        third_canonical_path,
        third_analysis,
    )

    before_bytes = (
        third_canonical_path
        .read_bytes()
    )

    raised = False

    try:

        apply_review_transition(
            case_id=
                real_case_id,

            record_type=
                "candidate",

            record_id=
                candidate_id,

            target_state=
                "confirmed",

            reviewer_ref=
                "test_reviewer",

            review_note=
                "Should rollback.",

            canonical_path=
                third_canonical_path,

            audit_dir=
                isolated_audit_dir,
        )

    except Exception:

        raised = True

    assert raised is True

    after_bytes = (
        third_canonical_path
        .read_bytes()
    )

    assert before_bytes == after_bytes, (
        "Rollback sonrası canonical dosya işlem ÖNCESİYLE "
        "byte-birebir aynı olmalıdır."
    )

    print(
        "T08 Rollback on post-write validation failure "
        "(stale input already present) restores canonical "
        "byte-for-byte:",
        "PASS"
    )

    # ========================================================
    # T09 CANONICAL case_0001/evidence/ NEVER TOUCHED
    # ========================================================

    real_canonical_path = (
        get_canonical_path(
            real_case_id
        )
    )

    assert not real_canonical_path.exists(), (
        "Self-test canonical case_0001/evidence/"
        "evidence.json dosyasını OLUŞTURMAMALIDIR."
    )

    print(
        "T09 Real canonical case_0001/evidence/ untouched "
        "throughout self-test:",
        "PASS"
    )

    temp_dir.cleanup()

    print()

    print(
        "======================================"
    )

    print(
        " EVIDENCE REVIEW V1: 9/9 SELF-TEST PASS"
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
            "Vergi AI Evidence Review V1 (Layer B)"
        )
    )

    parser.add_argument(
        "--case",
        dest="case_id",
        default=
            DEFAULT_CASE_ID,
    )

    parser.add_argument(
        "--confirm",
        dest="confirm_id",
        default=None,
        help="Confirm edilecek candidate_id.",
    )

    parser.add_argument(
        "--reject",
        dest="reject_id",
        default=None,
        help="Reject edilecek candidate_id.",
    )

    parser.add_argument(
        "--accept-follow-up",
        dest="accept_follow_up_id",
        default=None,
        help=(
            "accepted_for_follow_up yapılacak suggestion_id."
        ),
    )

    parser.add_argument(
        "--dismiss",
        dest="dismiss_id",
        default=None,
        help="Dismiss edilecek suggestion_id.",
    )

    parser.add_argument(
        "--reviewer",
        default="human_review",
    )

    parser.add_argument(
        "--note",
        default=(
            "Evidence Review V1 ile insan tarafından "
            "incelendi."
        ),
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
        dest="self_test",
    )

    args = parser.parse_args()

    if args.self_test:

        run_self_test()

        return

    mutation_requests = [
        (
            "candidate",
            args.confirm_id,
            "confirmed",
        ),

        (
            "candidate",
            args.reject_id,
            "rejected",
        ),

        (
            "suggestion",
            args.accept_follow_up_id,
            "accepted_for_follow_up",
        ),

        (
            "suggestion",
            args.dismiss_id,
            "dismissed",
        ),
    ]

    active_requests = [
        request
        for request in mutation_requests
        if request[
            1
        ]
        is not None
    ]

    if not active_requests:

        run_review_report(
            args.case_id
        )

        return

    if len(
        active_requests
    ) > 1:

        raise EvidenceReviewError(
            "Tek çalıştırmada yalnız BİR mutation flag'i "
            "verilebilir."
        )

    (
        record_type,
        record_id,
        target_state,
    ) = active_requests[
        0
    ]

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - EVIDENCE REVIEW V1 (LAYER B)"
    )

    print(
        " MODE: MUTATE"
    )

    print(
        "======================================"
    )

    result = apply_review_transition(
        case_id=
            args.case_id,

        record_type=
            record_type,

        record_id=
            record_id,

        target_state=
            target_state,

        reviewer_ref=
            args.reviewer,

        review_note=
            args.note,
    )

    print()

    print(
        "REVIEW TRANSITION APPLIED"
    )

    print(
        "Record:",
        record_id,
    )

    print(
        "Previous state:",
        result[
            "previous_state"
        ],
    )

    print(
        "New state:",
        result[
            "new_state"
        ],
    )

    print(
        "Pre SHA256:",
        result[
            "pre_sha256"
        ],
    )

    print(
        "Post SHA256:",
        result[
            "post_sha256"
        ],
    )

    print(
        "Audit:",
        result[
            "audit_path"
        ],
    )

    print()

    print(
        "SEMANTIC NOTE:"
    )

    print(
        "- 'confirmed' yalnız ilişkinin avukat tarafından "
        "doğrulandığını gösterir; admissibility/strength/"
        "sufficiency DEĞİLDİR."
    )

    print()

    print(
        "======================================"
    )

    print(
        " EVIDENCE REVIEW V1: PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        print()

        print(
            "ERROR:"
        )

        print(
            error
        )

        print()

        print(
            "======================================"
        )

        print(
            " EVIDENCE REVIEW V1: FAIL"
        )

        print(
            "======================================"
        )

        sys.exit(
            1
        )
