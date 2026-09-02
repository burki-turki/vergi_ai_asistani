# ============================================================
# VERGİ AI - ISSUE SPOTTING POLICY V1
#
# AMAÇ
# ----
#
# Canonical case facts, canonical timeline ve (varsa) canonical
# deadline analysis üzerinden, deterministik kurallarla
# hukuki ISSUE CANDIDATE'lar üretmek.
#
#
# TEMEL PRENSİP
# -------------
#
# Bu modül LLM KULLANMAZ. Yalnız canonical veri içindeki
# yapısal sinyallere (verification_state, calculation_state,
# fact_kind gibi) dayanan, tekrarlanabilir ve denetlenebilir
# kurallar uygular.
#
#
# ISSUE CANDIDATE NEDİR / NE DEĞİLDİR
# ------------------------------------
#
# Bir issue candidate:
#
#   != verified fact
#   != legal conclusion
#   != case outcome
#   != guaranteed applicability
#   != deadline determination
#
# Yalnızca "bu noktanın incelenmesi/doğrulanması gerekebilir"
# anlamına gelir. Bu nedenle her kural, description alanına
# kesin hukuki sonuç ifadesi (ör. "dava süresi geçmiştir")
# YAZAMAZ; bu Issue Spotting Validator V1 tarafından ayrıca
# denetlenir.
#
#
# KURALLAR (V1)
# -------------
#
# R1 - issue_rule_unverified_deadline_relevant_event_v1
#      Canonical timeline event deadline_relevant=True ve
#      verification_state != verified.
#
# R2 - issue_rule_blocked_unverified_anchor_deadline_v1
#      Canonical deadline calculation_state=
#      blocked_unverified_anchor.
#
# R3 - issue_rule_deadline_needs_further_review_v1
#      Canonical deadline calculation_state in
#      {blocked_missing_rule, blocked_ambiguous_rule,
#       needs_review}.
#
# R4 - issue_rule_legal_reference_fact_v1
#      Canonical fact fact_kind == legal_reference.
# ============================================================


# ============================================================
# VERSION
# ============================================================

ISSUE_SPOTTING_POLICY_VERSION = "1"


# ============================================================
# RULE IDS
# ============================================================

RULE_UNVERIFIED_DEADLINE_RELEVANT_EVENT = (
    "issue_rule_unverified_deadline_relevant_event_v1"
)

RULE_BLOCKED_UNVERIFIED_ANCHOR_DEADLINE = (
    "issue_rule_blocked_unverified_anchor_deadline_v1"
)

RULE_DEADLINE_NEEDS_FURTHER_REVIEW = (
    "issue_rule_deadline_needs_further_review_v1"
)

RULE_LEGAL_REFERENCE_FACT = (
    "issue_rule_legal_reference_fact_v1"
)


# ============================================================
# HELPERS
# ============================================================

def unique_strings(
    values,
):

    result = []

    for value in values:

        if (
            isinstance(
                value,
                str,
            )
            and value
            and value not in result
        ):

            result.append(
                value
            )

    return result


def safe_confidence(
    value,
):

    try:

        number = float(
            value
        )

    except (
        TypeError,
        ValueError,
    ):

        return 0.5

    return max(
        0.0,
        min(
            number,
            1.0,
        ),
    )


# ============================================================
# R1 - UNVERIFIED DEADLINE RELEVANT EVENT
# ============================================================

def apply_rule_unverified_deadline_relevant_event(
    timeline_events,
):

    candidates = []

    for event in timeline_events:

        if (
            event.get(
                "deadline_relevant"
            )
            is not True
        ):

            continue

        if (
            event.get(
                "verification_state"
            )
            == "verified"
        ):

            continue

        event_id = event.get(
            "event_id"
        )

        candidates.append(
            {
                "issue_type":
                    "verification_gap",

                "title":
                    (
                        "Süre açısından önemli olayın "
                        "doğrulanması gerekebilir"
                    ),

                "description":
                    (
                        f"{event.get('event_type')} tipindeki "
                        f"{event.get('date')} tarihli olay "
                        f"({event_id}) süre hesabı açısından "
                        "önemli olabilir; ancak "
                        "verification_state="
                        f"'{event.get('verification_state')}' "
                        "durumundadır. Bu tarihin bağımsız "
                        "olarak doğrulanması önerilir."
                    ),

                "trigger_rule_id":
                    RULE_UNVERIFIED_DEADLINE_RELEVANT_EVENT,

                "source_fact_ids":
                    unique_strings(
                        event.get(
                            "source_fact_ids",
                            [],
                        )
                    ),

                "source_timeline_event_ids": [
                    event_id
                ],

                "source_deadline_ids": [],

                "related_party_ids":
                    unique_strings(
                        event.get(
                            "related_party_ids",
                            [],
                        )
                    ),

                "related_dispute_item_ids":
                    unique_strings(
                        event.get(
                            "related_dispute_item_ids",
                            [],
                        )
                    ),

                "confidence":
                    safe_confidence(
                        event.get(
                            "confidence"
                        )
                    ),

                "requires_human_review":
                    True,

                "notes":
                    None,
            }
        )

    return candidates


# ============================================================
# R2 - BLOCKED UNVERIFIED ANCHOR DEADLINE
# ============================================================

def apply_rule_blocked_unverified_anchor_deadline(
    deadlines,
    event_index,
):

    candidates = []

    for deadline in deadlines:

        if (
            deadline.get(
                "calculation_state"
            )
            != "blocked_unverified_anchor"
        ):

            continue

        deadline_id = deadline.get(
            "deadline_id"
        )

        anchor_event_id = deadline.get(
            "anchor_event_id"
        )

        anchor_event = event_index.get(
            anchor_event_id,
            {},
        )

        candidates.append(
            {
                "issue_type":
                    "deadline_risk",

                "title":
                    (
                        "Süre hesaplaması doğrulanmamış "
                        "olay nedeniyle bloklanmıştır"
                    ),

                "description":
                    (
                        f"{deadline_id} kaydı için süre "
                        "hesaplaması, "
                        f"anchor_event_id={anchor_event_id} "
                        "olayının doğrulanmamış olması "
                        "nedeniyle yapılamamıştır. Bu durum "
                        "davanın süresinde açılıp "
                        "açılmadığına dair bir belirleme "
                        "içermez; yalnızca anchor olayın "
                        "bağımsız olarak doğrulanması "
                        "gerektiğini gösterir."
                    ),

                "trigger_rule_id":
                    RULE_BLOCKED_UNVERIFIED_ANCHOR_DEADLINE,

                "source_fact_ids":
                    unique_strings(
                        anchor_event.get(
                            "source_fact_ids",
                            [],
                        )
                    ),

                "source_timeline_event_ids":
                    unique_strings(
                        [
                            anchor_event_id
                        ]
                    ),

                "source_deadline_ids": [
                    deadline_id
                ],

                "related_party_ids":
                    unique_strings(
                        anchor_event.get(
                            "related_party_ids",
                            [],
                        )
                    ),

                "related_dispute_item_ids":
                    unique_strings(
                        anchor_event.get(
                            "related_dispute_item_ids",
                            [],
                        )
                    ),

                "confidence":
                    safe_confidence(
                        deadline.get(
                            "confidence"
                        )
                    ),

                "requires_human_review":
                    True,

                "notes":
                    None,
            }
        )

    return candidates


# ============================================================
# R3 - DEADLINE NEEDS FURTHER REVIEW
# ============================================================

def apply_rule_deadline_needs_further_review(
    deadlines,
    event_index,
):

    other_blocked_states = {
        "blocked_missing_rule",
        "blocked_ambiguous_rule",
        "needs_review",
    }

    candidates = []

    for deadline in deadlines:

        calculation_state = (
            deadline.get(
                "calculation_state"
            )
        )

        if (
            calculation_state
            not in other_blocked_states
        ):

            continue

        deadline_id = deadline.get(
            "deadline_id"
        )

        anchor_event_id = deadline.get(
            "anchor_event_id"
        )

        anchor_event = event_index.get(
            anchor_event_id,
            {},
        )

        candidates.append(
            {
                "issue_type":
                    "deadline_risk",

                "title":
                    (
                        "Süre hesaplaması ek inceleme "
                        "gerektirmektedir"
                    ),

                "description":
                    (
                        f"{deadline_id} kaydı "
                        f"calculation_state="
                        f"'{calculation_state}' durumundadır "
                        "ve kesin bir süre hesabı "
                        "üretilmemiştir. Bu kaydın ayrıca "
                        "incelenmesi önerilir."
                    ),

                "trigger_rule_id":
                    RULE_DEADLINE_NEEDS_FURTHER_REVIEW,

                "source_fact_ids":
                    unique_strings(
                        anchor_event.get(
                            "source_fact_ids",
                            [],
                        )
                    ),

                "source_timeline_event_ids":
                    unique_strings(
                        [
                            anchor_event_id
                        ]
                        if anchor_event_id
                        else []
                    ),

                "source_deadline_ids": [
                    deadline_id
                ],

                "related_party_ids":
                    unique_strings(
                        anchor_event.get(
                            "related_party_ids",
                            [],
                        )
                    ),

                "related_dispute_item_ids":
                    unique_strings(
                        anchor_event.get(
                            "related_dispute_item_ids",
                            [],
                        )
                    ),

                "confidence":
                    safe_confidence(
                        deadline.get(
                            "confidence"
                        )
                    ),

                "requires_human_review":
                    True,

                "notes":
                    None,
            }
        )

    return candidates


# ============================================================
# R4 - LEGAL REFERENCE FACT
# ============================================================

def apply_rule_legal_reference_fact(
    fact_index,
):

    candidates = []

    for (
        fact_id,
        record,
    ) in fact_index.items():

        fact = record[
            "fact"
        ]

        if (
            fact.get(
                "fact_kind"
            )
            != "legal_reference"
        ):

            continue

        candidates.append(
            {
                "issue_type":
                    "legal_basis_reference",

                "title":
                    (
                        "Belgede atıf yapılan hukuki "
                        "dayanağın uygulanabilirliği "
                        "değerlendirilmelidir"
                    ),

                "description":
                    (
                        f"{fact_id} kaydında şu ifadeye yer "
                        f"verilmektedir: "
                        f"\"{fact.get('statement')}\" "
                        "Belgede bir hukuki dayanağa atıf "
                        "yapılmış olması, bu dayanağın "
                        "olaya uygulanabilirliğini, "
                        "yürürlüğünü veya doğruluğunu "
                        "tek başına göstermez; ayrıca "
                        "değerlendirilmesi önerilir."
                    ),

                "trigger_rule_id":
                    RULE_LEGAL_REFERENCE_FACT,

                "source_fact_ids": [
                    fact_id
                ],

                "source_timeline_event_ids": [],

                "source_deadline_ids": [],

                "related_party_ids":
                    unique_strings(
                        fact.get(
                            "related_party_ids",
                            [],
                        )
                    ),

                "related_dispute_item_ids":
                    unique_strings(
                        fact.get(
                            "related_dispute_item_ids",
                            [],
                        )
                    ),

                "confidence":
                    safe_confidence(
                        fact.get(
                            "confidence"
                        )
                    ),

                "requires_human_review":
                    True,

                "notes":
                    None,
            }
        )

    return candidates


# ============================================================
# RUN ALL RULES
# ============================================================

def run_all_rules(
    fact_index,
    timeline_events,
    event_index,
    deadlines,
):

    candidates = []

    candidates.extend(
        apply_rule_unverified_deadline_relevant_event(
            timeline_events
        )
    )

    candidates.extend(
        apply_rule_blocked_unverified_anchor_deadline(
            deadlines,
            event_index,
        )
    )

    candidates.extend(
        apply_rule_deadline_needs_further_review(
            deadlines,
            event_index,
        )
    )

    candidates.extend(
        apply_rule_legal_reference_fact(
            fact_index
        )
    )

    return candidates


# ============================================================
# FINALIZE CANDIDATES
#
# issue_id atar ve status="candidate" sabitler.
#
# Bu fonksiyon hem Issue Spotting Engine hem de Issue
# Spotting Validator self-test tarafından kullanılır; iki
# katmanın issue kaydı şeklinin birbirinden sapmasını önler.
# ============================================================

def finalize_candidates(
    candidates,
):

    finalized = []

    for index, candidate in enumerate(
        candidates,
        start=1,
    ):

        issue = dict(
            candidate
        )

        issue[
            "issue_id"
        ] = f"issue_{index:03d}"

        issue[
            "status"
        ] = "candidate"

        finalized.append(
            issue
        )

    return finalized
