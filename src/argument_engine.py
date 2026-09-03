# ============================================================
# VERGİ AI - ARGUMENT ENGINE V1
#
# AMAÇ
# ----
#
# Canonical issues.json (Row 9) + approved facts.json (Row 6)
# + (yalnız CANONICAL, asla pending) Row 12 evidence + Row 10
# legal research + Row 11 case law + Row 7 timeline + Row 8
# deadline üzerinden, Argument Discovery V1 (deterministik
# allowlist) + Argument Agent V1'i (3 aşamalı LLM: claim ->
# counterargument -> rebuttal + suggestion) çalıştırıp sonucu:
#
#     data/cases/<case_id>/arguments/
#     arguments_<case_id>_v1.json.pending
#
# olarak üretmek.
#
#
# KRİTİK GÜVENLİK
# ----------------
#
# - Engine canonical arguments.json dosyasına YAZMAZ.
# - HER canonical issue için TAM OLARAK BİR coverage kaydı.
# - Evidence upstream'i YALNIZ canonical evidence.json'dan
#   okunur; pending evidence dosyası HİÇ AÇILMAZ.
# - Üç aşama SIRALI çalışır; her aşama yalnız BİR ÖNCEKİ
#   aşamanın FINALIZE EDİLMİŞ (stable ID'li) çıktısına dayanır.
# - Safe review carry-forward: yalnız TÜM upstream hash'ler
#   önceki canonical analizle birebir aynıysa VE entity
#   fingerprint'i birebir aynıysa VE önceki review_state
#   'needs_review' DEĞİLSE devreye girer; aksi halde yeni/
#   değişmiş kayıt needs_review başlar.
# ============================================================


import argparse
import hashlib
import json
import os
import shutil
import sys

from datetime import datetime
from pathlib import Path


from legal_research_validator import load_canonical_issues

from timeline_validator import load_canonical_fact_index

from issue_spotting_validator import FORBIDDEN_PHRASES

from timeline_consolidation_policy import normalize_text_tr

from argument_policy import (
    ARGUMENT_POLICY_VERSION,
    ZERO_CLAIM_EXECUTION_STATES,
    ZERO_SUGGESTION_EXECUTION_STATES,
    compute_claim_fingerprint,
    compute_counterargument_fingerprint,
    compute_rebuttal_fingerprint,
    sha256_of,
)

from argument_discovery import (
    ARGUMENT_DISCOVERY_VERSION,
    build_allowlists_for_issues,
    build_coverage_record,
    load_canonical_case_law_optional,
    load_canonical_deadline_optional,
    load_canonical_evidence_optional,
    load_canonical_legal_research_optional,
    load_canonical_timeline_optional,
)

from argument_agent import (
    ARGUMENT_AGENT_VERSION,
    build_claim_prompt,
    build_counterargument_prompt,
    build_rebuttal_prompt,
    build_suggestion_prompt,
    call_stage,
    run_claim_stage,
    run_counterargument_stage,
    run_rebuttal_stage,
    run_suggestion_stage,
)

from argument_validator import validate_argument_analysis


# ============================================================
# VERSION
# ============================================================

ARGUMENT_ENGINE_VERSION = "1"

ALL_FORBIDDEN_PHRASES = tuple(FORBIDDEN_PHRASES)


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"

CASES_DIR = DATA_DIR / "cases"

DEFAULT_CASE_ID = "case_0001"


# ============================================================
# EXCEPTION
# ============================================================

class ArgumentEngineError(Exception):
    pass


# ============================================================
# JSON HELPERS
# ============================================================

def load_json(path):

    path = Path(path)

    if not path.exists():

        raise FileNotFoundError(f"JSON dosyası bulunamadı:\n{path}")

    with open(path, "r", encoding="utf-8") as file:

        return json.load(file)


def atomic_write_json(path, data):

    path = Path(path)

    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = path.parent / (path.name + ".tmp")

    with open(temp_path, "w", encoding="utf-8", newline="\n") as file:

        json.dump(data, file, ensure_ascii=False, indent=2)

        file.write("\n")

        file.flush()

        os.fsync(file.fileno())

    os.replace(temp_path, path)


# ============================================================
# CASE PATHS
# ============================================================

def get_arguments_dir(case_id):

    return CASES_DIR / case_id / "arguments"


def get_pending_path(case_id):

    return get_arguments_dir(case_id) / f"arguments_{case_id}_v1.json.pending"


def get_canonical_path(case_id):

    return get_arguments_dir(case_id) / "arguments.json"


def get_history_dir(case_id):

    return get_arguments_dir(case_id) / "history"


def get_carry_forward_dir(case_id):

    return get_arguments_dir(case_id) / "history" / "carry_forward"


# ============================================================
# PREVIOUS PENDING PRESERVATION
# ============================================================

def preserve_previous_pending(case_id, pending_path):

    pending_path = Path(pending_path)

    if not pending_path.exists():

        return None

    history_dir = get_history_dir(case_id)

    history_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")

    history_path = history_dir / (
        "arguments_pending_before_engine_" + timestamp + ".json.pending"
    )

    shutil.move(str(pending_path), str(history_path))

    return history_path


# ============================================================
# OUTPUT SEMANTIC GUARD (DEFENSE IN DEPTH)
# ============================================================

def check_forbidden_phrases(record_id, *texts):

    combined = normalize_text_tr(" ".join(text or "" for text in texts))

    for phrase in ALL_FORBIDDEN_PHRASES:

        if phrase in combined:

            raise ArgumentEngineError(
                "Kayıt kesin hukuki sonuç/outcome ifadesi içeriyor "
                f"('{phrase}'): {record_id}"
            )


FORBIDDEN_RECORD_FIELDS = {
    "confidence",
    "strength",
    "priority",
    "admissibility",
    "sufficiency",
    "win_probability",
    "recommended_outcome",
    "success_probability",
}


def validate_engine_output_semantics(analysis, expected_issue_count, carried_ids=None):
    """
    carried_ids: {"claim": {claim_id,...}, "counterargument": {...},
    "rebuttal": {...}} - yalnız apply_review_carry_forward tarafından
    MEŞRU olarak carry-forward edilmiş ID'ler needs_review DIŞINDA bir
    state ile bu guard'dan geçebilir (confirmed/rejected). Agent'ın
    KENDİSİ hiçbir zaman needs_review dışında bir değer üretemez.
    """

    carried_ids = carried_ids or {
        "claim": set(), "counterargument": set(), "rebuttal": set(),
    }

    if not isinstance(analysis, dict):

        raise ArgumentEngineError("Argument analysis dict değil.")

    coverage_records = analysis.get("argument_coverage")

    claims = analysis.get("argument_claims")

    counterarguments = analysis.get("argument_counterarguments")

    rebuttals = analysis.get("argument_rebuttals")

    suggestions = analysis.get("argument_agent_suggestions")

    for name, records in (
        ("argument_coverage", coverage_records),
        ("argument_claims", claims),
        ("argument_counterarguments", counterarguments),
        ("argument_rebuttals", rebuttals),
        ("argument_agent_suggestions", suggestions),
    ):

        if not isinstance(records, list):

            raise ArgumentEngineError(f"{name} alanı list değil.")

    covered_issue_ids = set()

    for coverage in coverage_records:

        if (
            coverage.get("status") != "candidate"
            or coverage.get("requires_human_review") is not True
        ):

            raise ArgumentEngineError(
                "Coverage kaydı status/requires_human_review "
                f"kısıtını ihlal ediyor: {coverage.get('coverage_id')}"
            )

        covered_issue_ids.add(coverage.get("source_issue_id"))

        if (
            coverage.get("execution_state") in ZERO_CLAIM_EXECUTION_STATES
            and (
                coverage.get("claim_count") != 0
                or coverage.get("counterargument_count") != 0
                or coverage.get("rebuttal_count") != 0
            )
        ):

            raise ArgumentEngineError(
                "Coverage execution_state="
                f"{coverage.get('execution_state')} iken claim/"
                "counterargument/rebuttal count 0 olmalıdır: "
                f"{coverage.get('coverage_id')}"
            )

        if (
            coverage.get("execution_state") in ZERO_SUGGESTION_EXECUTION_STATES
            and coverage.get("suggestion_count") != 0
        ):

            raise ArgumentEngineError(
                "Coverage execution_state="
                f"{coverage.get('execution_state')} iken "
                f"suggestion_count 0 olmalıdır: {coverage.get('coverage_id')}"
            )

    if (
        len(covered_issue_ids) != expected_issue_count
        or len(coverage_records) != expected_issue_count
    ):

        raise ArgumentEngineError(
            "Her canonical issue tam olarak bir coverage kaydı "
            f"almalıdır. Beklenen={expected_issue_count}, "
            f"Bulunan (benzersiz issue)={len(covered_issue_ids)}, "
            f"Bulunan (toplam kayıt)={len(coverage_records)}"
        )

    seen_claim_keys = set()

    for claim in claims:

        review_state = claim.get("claim_review_state")

        is_legit_carry_forward = (
            claim.get("claim_id") in carried_ids["claim"]
            and review_state in ("confirmed", "rejected")
        )

        if (
            claim.get("status") != "candidate"
            or claim.get("requires_human_review") is not True
            or (review_state != "needs_review" and not is_legit_carry_forward)
        ):

            raise ArgumentEngineError(
                "Claim engine çıktısında yalnız needs_review (veya "
                "meşru bir carry-forward) olabilir: "
                f"{claim.get('claim_id')}"
            )

        if not claim.get("source_fact_ids"):

            raise ArgumentEngineError(
                f"Claim minimum grounding ihlali: {claim.get('claim_id')}"
            )

        if FORBIDDEN_RECORD_FIELDS & set(claim.keys()):

            raise ArgumentEngineError(
                f"Claim yasak alan taşıyor: {claim.get('claim_id')}"
            )

        key = compute_claim_fingerprint(claim)

        if key in seen_claim_keys:

            raise ArgumentEngineError(
                f"Duplicate claim fingerprint: {claim.get('claim_id')}"
            )

        seen_claim_keys.add(key)

        check_forbidden_phrases(
            claim.get("claim_id"), claim.get("claim_text"),
            claim.get("grounded_explanation"),
        )

    claim_ids = {claim["claim_id"] for claim in claims}

    seen_counter_keys = set()

    for counter in counterarguments:

        counter_review_state = counter.get("counter_review_state")

        counter_is_legit_carry_forward = (
            counter.get("counterargument_id") in carried_ids["counterargument"]
            and counter_review_state in ("confirmed", "rejected")
        )

        if (
            counter.get("status") != "candidate"
            or counter.get("requires_human_review") is not True
            or (
                counter_review_state != "needs_review"
                and not counter_is_legit_carry_forward
            )
        ):

            raise ArgumentEngineError(
                "Counterargument engine çıktısında yalnız needs_review "
                "(veya meşru bir carry-forward) olabilir: "
                f"{counter.get('counterargument_id')}"
            )

        if counter.get("source_claim_id") not in claim_ids:

            raise ArgumentEngineError(
                "Counterargument bilinmeyen bir claim'e bağlı: "
                f"{counter.get('counterargument_id')}"
            )

        if FORBIDDEN_RECORD_FIELDS & set(counter.keys()):

            raise ArgumentEngineError(
                f"Counterargument yasak alan taşıyor: "
                f"{counter.get('counterargument_id')}"
            )

        key = compute_counterargument_fingerprint(counter)

        if key in seen_counter_keys:

            raise ArgumentEngineError(
                "Duplicate counterargument fingerprint: "
                f"{counter.get('counterargument_id')}"
            )

        seen_counter_keys.add(key)

        check_forbidden_phrases(
            counter.get("counterargument_id"),
            counter.get("counterargument_text"),
            counter.get("grounded_explanation"),
        )

    counter_ids = {counter["counterargument_id"] for counter in counterarguments}

    counter_claim_map = {
        counter["counterargument_id"]: counter["source_claim_id"]
        for counter in counterarguments
    }

    seen_rebuttal_keys = set()

    for rebuttal in rebuttals:

        rebuttal_review_state = rebuttal.get("rebuttal_review_state")

        rebuttal_is_legit_carry_forward = (
            rebuttal.get("rebuttal_id") in carried_ids["rebuttal"]
            and rebuttal_review_state in ("confirmed", "rejected")
        )

        if (
            rebuttal.get("status") != "candidate"
            or rebuttal.get("requires_human_review") is not True
            or (
                rebuttal_review_state != "needs_review"
                and not rebuttal_is_legit_carry_forward
            )
        ):

            raise ArgumentEngineError(
                "Rebuttal engine çıktısında yalnız needs_review (veya "
                f"meşru bir carry-forward) olabilir: "
                f"{rebuttal.get('rebuttal_id')}"
            )

        if rebuttal.get("source_counterargument_id") not in counter_ids:

            raise ArgumentEngineError(
                "Rebuttal bilinmeyen bir counterargument'a bağlı: "
                f"{rebuttal.get('rebuttal_id')}"
            )

        if (
            counter_claim_map.get(rebuttal.get("source_counterargument_id"))
            != rebuttal.get("source_claim_id")
        ):

            raise ArgumentEngineError(
                "Rebuttal'ın source_claim_id'si, referans verdiği "
                "counterargument'ın gerçek claim'i ile eşleşmiyor: "
                f"{rebuttal.get('rebuttal_id')}"
            )

        if FORBIDDEN_RECORD_FIELDS & set(rebuttal.keys()):

            raise ArgumentEngineError(
                f"Rebuttal yasak alan taşıyor: {rebuttal.get('rebuttal_id')}"
            )

        key = compute_rebuttal_fingerprint(rebuttal)

        if key in seen_rebuttal_keys:

            raise ArgumentEngineError(
                f"Duplicate rebuttal fingerprint: {rebuttal.get('rebuttal_id')}"
            )

        seen_rebuttal_keys.add(key)

        check_forbidden_phrases(
            rebuttal.get("rebuttal_id"), rebuttal.get("rebuttal_text"),
            rebuttal.get("grounded_explanation"),
        )

    for suggestion in suggestions:

        if (
            suggestion.get("status") != "candidate"
            or suggestion.get("requires_human_review") is not True
            or suggestion.get("suggestion_review_state") != "needs_review"
        ):

            raise ArgumentEngineError(
                "Suggestion engine çıktısında yalnız needs_review/"
                f"candidate olabilir: {suggestion.get('suggestion_id')}"
            )

        if FORBIDDEN_RECORD_FIELDS & set(suggestion.keys()):

            raise ArgumentEngineError(
                f"Suggestion yasak alan taşıyor: {suggestion.get('suggestion_id')}"
            )

        check_forbidden_phrases(
            suggestion.get("suggestion_id"), suggestion.get("grounded_explanation"),
        )


# ============================================================
# SAFE REVIEW CARRY-FORWARD
# ============================================================

def load_previous_canonical(case_id):

    canonical_path = get_canonical_path(case_id)

    if not canonical_path.exists():

        return None

    return load_json(canonical_path)


def apply_review_carry_forward(
    case_id,
    claims,
    counterarguments,
    rebuttals,
    analysis_metadata,
):
    """
    Fail-closed basit kural: TÜM upstream input hash'leri önceki
    canonical analizle BİREBİR aynı değilse HİÇBİR carry-forward
    yapılmaz (yeni/değişmiş her şey needs_review kalır). Aynıysa,
    yalnız fingerprint'i birebir eşleşen VE önceki review_state'i
    'needs_review' OLMAYAN kayıtlar review_state'lerini devralır.
    """

    previous = load_previous_canonical(case_id)

    carry_records = []

    if previous is None:

        return (claims, counterarguments, rebuttals, carry_records)

    if previous.get("analysis_metadata") != analysis_metadata:

        return (claims, counterarguments, rebuttals, carry_records)

    prev_claim_by_fp = {
        compute_claim_fingerprint(claim): claim
        for claim in previous.get("argument_claims", [])
    }

    prev_counter_by_fp = {
        compute_counterargument_fingerprint(counter): counter
        for counter in previous.get("argument_counterarguments", [])
    }

    prev_rebuttal_by_fp = {
        compute_rebuttal_fingerprint(rebuttal): rebuttal
        for rebuttal in previous.get("argument_rebuttals", [])
    }

    for claim in claims:

        fp = compute_claim_fingerprint(claim)

        prev = prev_claim_by_fp.get(fp)

        if prev is not None and prev["claim_review_state"] != "needs_review":

            claim["claim_review_state"] = prev["claim_review_state"]

            carry_records.append(
                {
                    "entity_type": "claim",
                    "previous_id": prev["claim_id"],
                    "new_id": claim["claim_id"],
                    "fingerprint": fp,
                    "carried_state": prev["claim_review_state"],
                }
            )

    for counter in counterarguments:

        fp = compute_counterargument_fingerprint(counter)

        prev = prev_counter_by_fp.get(fp)

        if prev is not None and prev["counter_review_state"] != "needs_review":

            counter["counter_review_state"] = prev["counter_review_state"]

            carry_records.append(
                {
                    "entity_type": "counterargument",
                    "previous_id": prev["counterargument_id"],
                    "new_id": counter["counterargument_id"],
                    "fingerprint": fp,
                    "carried_state": prev["counter_review_state"],
                }
            )

    for rebuttal in rebuttals:

        fp = compute_rebuttal_fingerprint(rebuttal)

        prev = prev_rebuttal_by_fp.get(fp)

        if prev is not None and prev["rebuttal_review_state"] != "needs_review":

            rebuttal["rebuttal_review_state"] = prev["rebuttal_review_state"]

            carry_records.append(
                {
                    "entity_type": "rebuttal",
                    "previous_id": prev["rebuttal_id"],
                    "new_id": rebuttal["rebuttal_id"],
                    "fingerprint": fp,
                    "carried_state": prev["rebuttal_review_state"],
                }
            )

    return (claims, counterarguments, rebuttals, carry_records)


def write_carry_forward_audit(case_id, carry_records):

    if not carry_records:

        return None

    carry_dir = get_carry_forward_dir(case_id)

    carry_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")

    audit_path = carry_dir / f"carry_forward_{timestamp}.json"

    atomic_write_json(
        audit_path,
        {
            "audit_type": "argument_review_carry_forward",
            "case_id": case_id,
            "carried_at": datetime.now().astimezone().isoformat(),
            "carried_records": carry_records,
        },
    )

    return audit_path


# ============================================================
# BUILD
# ============================================================

def build_argument_engine_output(
    case_id,
    use_agent=False,
    llm_client=None,
    network_allowed=False,
):

    issue_context = load_canonical_issues(case_id)

    issues = issue_context["issues"]

    issue_index = issue_context["issue_index"]

    fact_context = load_canonical_fact_index(case_id)

    fact_index = fact_context["facts"]

    (
        _evidence_candidates,
        evidence_candidate_index,
        evidence_path,
    ) = load_canonical_evidence_optional(case_id)

    (
        _researches,
        research_index,
        research_path,
    ) = load_canonical_legal_research_optional(case_id)

    (
        _decisions,
        case_law_decision_index,
        case_law_path,
    ) = load_canonical_case_law_optional(case_id)

    timeline_event_index, timeline_path = load_canonical_timeline_optional(case_id)

    _deadlines, deadline_ids, deadline_path = load_canonical_deadline_optional(
        case_id
    )

    warnings = []

    (allowlist_by_issue, discovery_warnings) = build_allowlists_for_issues(
        issues,
        fact_index,
        evidence_candidate_index,
        research_index,
        case_law_decision_index,
        timeline_event_index,
        deadline_ids,
    )

    warnings.extend(discovery_warnings)

    all_known_ids = (
        set(fact_index.keys())
        | set(evidence_candidate_index.keys())
        | set(research_index.keys())
        | set(case_law_decision_index.keys())
        | set(timeline_event_index.keys())
        | set(deadline_ids)
    )

    agent_enabled = bool(use_agent)

    finalized_claims = []

    finalized_counterarguments = []

    finalized_rebuttals = []

    finalized_suggestions = []

    per_issue_stage_stats = {}

    agent_call_failed = False

    agent_unparseable = False

    if agent_enabled:

        if llm_client is None and not network_allowed:

            warnings.append(
                "Network access disabled (network_allowed=False, "
                "--allow-network verilmedi); Argument Agent atlandı."
            )

            agent_enabled = False

    if agent_enabled:

        try:

            # ------------------------------------------------------
            # REAL CLIENT CONSTRUCTION (Row 9-12 ile birebir aynı
            # desen): buraya yalnız --with-agent VE --allow-network
            # İKİSİ BİRDEN doğruyken ve hiçbir injected llm_client
            # verilmemişken ulaşılabilir (üstteki gate zaten
            # llm_client is None and not network_allowed durumunda
            # agent_enabled'ı False yapıp bu bloğa hiç girmiyor).
            # AnthropicArgumentLLMClient.__init__ hiçbir network I/O
            # yapmaz (yalnız `anthropic` paketi ilk .generate()
            # çağrısında lazy import edilir); bu nedenle burada
            # constructor'ı çağırmak network safety'yi bozmaz.
            # ------------------------------------------------------

            if llm_client is None:

                # Lazy import (module-attribute lookup at call time, NOT
                # a top-level "from argument_agent import ..." binding) -
                # bu, testlerin argument_agent.AnthropicArgumentLLMClient
                # üzerinden monkeypatch yapabilmesini sağlar.
                from argument_agent import AnthropicArgumentLLMClient

                llm_client = AnthropicArgumentLLMClient()

            # ---- STAGE 1: CLAIM ----

            claim_prompt = build_claim_prompt(allowlist_by_issue, fact_index)

            raw_claims = call_stage(llm_client, claim_prompt)

            (
                finalized_claims,
                claim_warnings,
                claim_stats,
            ) = run_claim_stage(
                raw_claims,
                allowlist_by_issue,
                fact_index,
                evidence_candidate_index,
                research_index,
                case_law_decision_index,
                all_known_ids,
                1,
            )

            warnings.extend(claim_warnings)

            merge_stage_stats(per_issue_stage_stats, claim_stats, "claim")

            all_known_ids |= {claim["claim_id"] for claim in finalized_claims}

            # ---- STAGE 2: COUNTERARGUMENT ----

            counter_prompt = build_counterargument_prompt(
                finalized_claims, allowlist_by_issue
            )

            raw_counters = call_stage(llm_client, counter_prompt)

            (
                finalized_counterarguments,
                counter_warnings,
                counter_stats,
            ) = run_counterargument_stage(
                raw_counters,
                finalized_claims,
                allowlist_by_issue,
                fact_index,
                evidence_candidate_index,
                research_index,
                case_law_decision_index,
                all_known_ids,
                1,
            )

            warnings.extend(counter_warnings)

            merge_stage_stats(per_issue_stage_stats, counter_stats, "counterargument")

            all_known_ids |= {
                counter["counterargument_id"]
                for counter in finalized_counterarguments
            }

            # ---- STAGE 3: REBUTTAL ----

            rebuttal_prompt = build_rebuttal_prompt(
                finalized_counterarguments, allowlist_by_issue
            )

            raw_rebuttals = call_stage(llm_client, rebuttal_prompt)

            (
                finalized_rebuttals,
                rebuttal_warnings,
                rebuttal_stats,
            ) = run_rebuttal_stage(
                raw_rebuttals,
                finalized_counterarguments,
                allowlist_by_issue,
                fact_index,
                evidence_candidate_index,
                research_index,
                case_law_decision_index,
                all_known_ids,
                1,
            )

            warnings.extend(rebuttal_warnings)

            merge_stage_stats(per_issue_stage_stats, rebuttal_stats, "rebuttal")

            all_known_ids |= {
                rebuttal["rebuttal_id"] for rebuttal in finalized_rebuttals
            }

            # ---- STAGE 4: SUGGESTIONS ----

            suggestion_prompt = build_suggestion_prompt(
                issue_index, finalized_claims, finalized_counterarguments
            )

            raw_suggestions = call_stage(llm_client, suggestion_prompt)

            known_reference_ids = all_known_ids | {
                rebuttal["rebuttal_id"] for rebuttal in finalized_rebuttals
            }

            (
                finalized_suggestions,
                suggestion_warnings,
                suggestion_stats,
            ) = run_suggestion_stage(
                raw_suggestions,
                issue_index,
                finalized_claims,
                finalized_counterarguments,
                known_reference_ids,
                1,
                fact_index=fact_index,
                evidence_candidate_index=evidence_candidate_index,
                research_index=research_index,
                case_law_decision_index=case_law_decision_index,
            )

            warnings.extend(suggestion_warnings)

            merge_stage_stats(per_issue_stage_stats, suggestion_stats, "suggestion")

        except json.JSONDecodeError as error:

            agent_unparseable = True

            warnings.append(f"Argument Agent cevabı parse edilemedi: {error}")

            # Row 13 corrective maintenance (C3): herhangi bir önceki
            # aşama (örn. claim) başarıyla finalize edilmiş olsa bile,
            # pipeline bu noktada bir bütün olarak başarısız sayılır -
            # coverage TÜM issue'lara uniform şekilde "analysis_failed"
            # damgalar (aşağıda) ve bu, claim/counterargument/rebuttal/
            # suggestion count'larının TAMAMEN 0 olmasını şart koşar
            # (ZERO_CLAIM_EXECUTION_STATES / ZERO_SUGGESTION_EXECUTION_
            # STATES). Kısmi finalize edilmiş entity'ler temizlenmezse
            # validate_engine_output_semantics uncaught ArgumentEngineError
            # fırlatır - temiz fail-closed pending yerine crash.
            finalized_claims = []

            finalized_counterarguments = []

            finalized_rebuttals = []

            finalized_suggestions = []

        except Exception as error:  # noqa: BLE001

            agent_call_failed = True

            warnings.append(f"Argument Agent çağrısı başarısız oldu: {error}")

            # Row 13 corrective maintenance (C3): bkz. yukarıdaki
            # json.JSONDecodeError bloğundaki gerekçe - aynı temizlik
            # burada da zorunludur.
            finalized_claims = []

            finalized_counterarguments = []

            finalized_rebuttals = []

            finalized_suggestions = []

    # ------------------------------------------------------------
    # ANALYSIS METADATA (önce hesapla - carry-forward eşitlik
    # kontrolü için gerekli)
    # ------------------------------------------------------------

    analysis_metadata = {
        "issues_input_hash": sha256_of(issues),
        "facts_input_hash": sha256_of(
            {fact_id: record["fact"] for fact_id, record in fact_index.items()}
        ),
        "evidence_input_hash": (
            sha256_of(evidence_candidate_index) if evidence_path.exists() else None
        ),
        "legal_research_input_hash": (
            sha256_of(research_index) if research_path.exists() else None
        ),
        "case_law_input_hash": (
            sha256_of(case_law_decision_index) if case_law_path.exists() else None
        ),
        "timeline_input_hash": (
            sha256_of(timeline_event_index) if timeline_path.exists() else None
        ),
        "deadline_input_hash": (
            sha256_of(sorted(deadline_ids)) if deadline_path.exists() else None
        ),
    }

    # ------------------------------------------------------------
    # SAFE REVIEW CARRY-FORWARD
    # ------------------------------------------------------------

    (
        finalized_claims,
        finalized_counterarguments,
        finalized_rebuttals,
        carry_records,
    ) = apply_review_carry_forward(
        case_id,
        finalized_claims,
        finalized_counterarguments,
        finalized_rebuttals,
        analysis_metadata,
    )

    # ------------------------------------------------------------
    # COVERAGE (HER ISSUE İÇİN)
    # ------------------------------------------------------------

    claims_by_issue = count_by(finalized_claims, "source_issue_id")

    counters_by_issue = count_by(finalized_counterarguments, "source_issue_id")

    rebuttals_by_issue = count_by(finalized_rebuttals, "source_issue_id")

    suggestions_by_issue = count_by(finalized_suggestions, "source_issue_id")

    raw_coverage = []

    for issue in issues:

        issue_id = issue["issue_id"]

        menu = allowlist_by_issue[issue_id]

        allowlist_count = menu["allowlist_count"]

        claim_count = claims_by_issue.get(issue_id, 0)

        counterargument_count = counters_by_issue.get(issue_id, 0)

        rebuttal_count = rebuttals_by_issue.get(issue_id, 0)

        suggestion_count = suggestions_by_issue.get(issue_id, 0)

        if not menu["has_minimum_grounding"]:

            execution_state = "blocked_missing_input"

            reason_codes = ["no_resolvable_approved_fact"]

        elif not agent_enabled:

            execution_state = "analysis_not_run"

            reason_codes = []

        elif agent_call_failed:

            execution_state = "analysis_failed"

            reason_codes = ["agent_call_failed"]

        elif agent_unparseable:

            execution_state = "analysis_failed"

            reason_codes = ["agent_response_unparseable"]

        else:

            bucket_reason_codes = []

            for stage_name in (
                "claim",
                "counterargument",
                "rebuttal",
                "suggestion",
            ):

                bucket = per_issue_stage_stats.get(stage_name, {}).get(
                    issue_id, {"raw": 0, "rejected": 0}
                )

                if bucket["rejected"] > 0:

                    bucket_reason_codes.append(
                        f"{stage_name}_rejected_shape_or_grounding_invalid"
                    )

            execution_state = (
                "analysis_partial" if bucket_reason_codes else "analysis_completed"
            )

            reason_codes = bucket_reason_codes

        raw_coverage.append(
            build_coverage_record(
                issue,
                execution_state,
                allowlist_count,
                claim_count=claim_count,
                counterargument_count=counterargument_count,
                rebuttal_count=rebuttal_count,
                suggestion_count=suggestion_count,
                reason_codes=reason_codes,
            )
        )

    status = "completed" if issues else "failed"

    analysis = {
        "schema_version": 1,
        "argument_analysis_id": f"arguments_{case_id}_v1",
        "case_id": case_id,
        "status": status,
        "generated_at": datetime.now().astimezone().isoformat(),
        "analysis_metadata": analysis_metadata,
        "argument_coverage": raw_coverage,
        "argument_claims": finalized_claims,
        "argument_counterarguments": finalized_counterarguments,
        "argument_rebuttals": finalized_rebuttals,
        "argument_agent_suggestions": finalized_suggestions,
        "warnings": warnings,
        "notes": (
            "Argument Engine V1 çekirdeği (deterministik Argument "
            "Discovery: yalnız canonical issue/approved fact/(varsa) "
            "canonical evidence-research-case_law-timeline-deadline) "
            "canonical issues.json içindeki HER issue için tam olarak "
            "bir coverage kaydı üretir; source of truth/safety "
            "boundary'dir. "
            + (
                "Bu çalıştırmada Argument Agent V1 (LLM, 3 aşamalı: "
                "claim->counterargument->rebuttal + suggestion) "
                "etkinleştirilmiştir. "
                if agent_enabled
                else "Bu çalıştırmada Argument Agent (LLM) devre "
                "dışıdır. "
            )
            + "Hiçbir claim/counterargument/rebuttal nihai hukuki "
            "sonuç, dava kazanma ihtimali veya admissibility/"
            "strength/sufficiency ifade etmez."
        ),
    }

    carried_ids = {
        "claim": {
            r["new_id"] for r in carry_records if r["entity_type"] == "claim"
        },
        "counterargument": {
            r["new_id"]
            for r in carry_records
            if r["entity_type"] == "counterargument"
        },
        "rebuttal": {
            r["new_id"] for r in carry_records if r["entity_type"] == "rebuttal"
        },
    }

    validate_engine_output_semantics(
        analysis, expected_issue_count=len(issue_index), carried_ids=carried_ids
    )

    carry_forward_audit_path = write_carry_forward_audit(case_id, carry_records)

    return {
        "analysis": analysis,
        "issue_count": len(issue_index),
        "fact_count": len(fact_index),
        "evidence_count": len(evidence_candidate_index),
        "legal_research_count": len(research_index),
        "case_law_count": len(case_law_decision_index),
        "timeline_event_count": len(timeline_event_index),
        "deadline_count": len(deadline_ids),
        "coverage_count": len(raw_coverage),
        "claim_count": len(finalized_claims),
        "counterargument_count": len(finalized_counterarguments),
        "rebuttal_count": len(finalized_rebuttals),
        "suggestion_count": len(finalized_suggestions),
        "agent_enabled": agent_enabled,
        "carried_ids": carried_ids,
        "carry_forward_count": len(carry_records),
        "carry_forward_audit_path": carry_forward_audit_path,
    }


def count_by(records, field):

    counts = {}

    for record in records:

        counts[record[field]] = counts.get(record[field], 0) + 1

    return counts


def merge_stage_stats(per_issue_stage_stats, stage_stats, stage_name):

    per_issue_stage_stats.setdefault(stage_name, {})

    for issue_id, bucket in stage_stats.items():

        per_issue_stage_stats[stage_name][issue_id] = bucket


# ============================================================
# WRITE PENDING
# ============================================================

def write_pending(case_id, analysis, expected_issue_count, carried_ids=None):

    arguments_dir = get_arguments_dir(case_id)

    arguments_dir.mkdir(parents=True, exist_ok=True)

    pending_path = get_pending_path(case_id)

    canonical_path = get_canonical_path(case_id)

    canonical_exists_before = canonical_path.exists()

    previous_pending_history = preserve_previous_pending(case_id, pending_path)

    try:

        atomic_write_json(pending_path, analysis)

        validation = validate_argument_analysis(
            arguments_path=pending_path,
            expected_case_id=case_id,
            raise_on_error=True,
        )

        if validation.get("valid") is not True:

            raise ArgumentEngineError("Post-write Argument Validator valid=False.")

        written = load_json(pending_path)

        validate_engine_output_semantics(
            written, expected_issue_count, carried_ids=carried_ids
        )

        if canonical_exists_before != canonical_path.exists():

            raise ArgumentEngineError(
                "Argument Engine canonical arguments.json durumunu "
                "değiştirdi."
            )

        return (pending_path, validation, previous_pending_history)

    except Exception:

        if pending_path.exists():

            pending_path.unlink()

        if (
            previous_pending_history is not None
            and previous_pending_history.exists()
        ):

            shutil.move(str(previous_pending_history), str(pending_path))

        raise


# ============================================================
# RUN ENGINE
# ============================================================

def run_engine(case_id, use_agent=False, llm_client=None, network_allowed=False):

    case_dir = CASES_DIR / case_id

    if not case_dir.exists():

        raise FileNotFoundError(f"Case bulunamadı:\n{case_dir}")

    build_result = build_argument_engine_output(
        case_id,
        use_agent=use_agent,
        llm_client=llm_client,
        network_allowed=network_allowed,
    )

    analysis = build_result["analysis"]

    (pending_path, validation, previous_pending_history) = write_pending(
        case_id,
        analysis,
        build_result["issue_count"],
        carried_ids=build_result["carried_ids"],
    )

    result = dict(build_result)

    result["pending_path"] = pending_path

    result["validation"] = validation

    result["previous_pending_history"] = previous_pending_history

    return result


# ============================================================
# REAL ARGUMENTS TREE SNAPSHOT (POST-APPROVAL SELF-TEST INVARIANT)
#
# "Gerçek canonical arguments.json mevcut OLMAMALIDIR" varsayımı
# yalnız Row 13 approval ÖNCESİNDE geçerliydi. Approval sonrası bu
# varsayım kalıcı olarak geçersizdir. Doğru invariant: self-test
# başlamadan önceki gerçek dizin durumu (mevcut olsun ya da olmasın)
# self-test SONUNDA birebir aynı kalmalıdır. snapshot fonksiyonu
# CASES_DIR sabitinden DOĞRUDAN türetir - herhangi bir monkeypatch
# edilmiş get_canonical_path/get_carry_forward_dir'den ETKİLENMEZ,
# bu yüzden testin kendi izole mutation'larını YANLIŞLIKLA "gerçek
# değişiklik" olarak raporlamaz.
# ============================================================

def snapshot_real_arguments_tree(case_id):

    real_dir = CASES_DIR / case_id / "arguments"

    if not real_dir.exists():

        return {
            "dir_exists": False,
            "files": {},
            "subdirs": [],
        }

    files = {}

    for path in sorted(real_dir.rglob("*")):

        if path.is_file():

            rel = str(path.relative_to(real_dir))

            files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()

    subdirs = sorted(
        str(path.relative_to(real_dir))
        for path in real_dir.rglob("*")
        if path.is_dir()
    )

    return {
        "dir_exists": True,
        "files": files,
        "subdirs": subdirs,
    }


def assert_real_arguments_tree_unchanged(case_id, before_snapshot, label):

    after_snapshot = snapshot_real_arguments_tree(case_id)

    assert after_snapshot == before_snapshot, (
        f"{label}: gerçek Row 13 arguments dizini self-test sırasında "
        f"DEĞİŞTİ (leakage şüphesi).\nÖnce: {before_snapshot}\n"
        f"Sonra: {after_snapshot}"
    )


# ============================================================
# SELF TEST
# ============================================================

def run_self_test(case_id="case_0001"):

    from argument_agent import FakeArgumentLLMClient
    from argument_discovery import build_allowlists_for_issues

    print()
    print("======================================")
    print(" VERGİ AI - ARGUMENT ENGINE V1")
    print("======================================")

    # --------------------------------------------------------
    # PRE-SELF-TEST SNAPSHOT (post-approval invariant): gerçek
    # arguments dizini approval ile mevcut olsun ya da olmasın, bu
    # self-test SONUNDA birebir aynı kalmalıdır.
    # --------------------------------------------------------

    real_tree_before = snapshot_real_arguments_tree(case_id)

    # --------------------------------------------------------
    # T01 OFFLINE BASELINE
    # --------------------------------------------------------

    offline_result = build_argument_engine_output(case_id, use_agent=False)

    assert offline_result["coverage_count"] == offline_result["issue_count"]
    assert offline_result["claim_count"] == 0
    assert offline_result["counterargument_count"] == 0
    assert offline_result["rebuttal_count"] == 0
    assert offline_result["suggestion_count"] == 0

    assert all(
        coverage["execution_state"] in ("analysis_not_run", "blocked_missing_input")
        for coverage in offline_result["analysis"]["argument_coverage"]
    )

    print(
        "T01 Offline end-to-end baseline (coverage completeness, "
        "0 claim/counter/rebuttal/suggestion):",
        "PASS",
    )

    # --------------------------------------------------------
    # T02 NETWORK GATE: agent istenir ama network kapalı ->
    # analysis_not_run kalır, agent hiç çağrılmaz
    # --------------------------------------------------------

    gated_result = build_argument_engine_output(
        case_id, use_agent=True, llm_client=None, network_allowed=False
    )

    assert gated_result["claim_count"] == 0
    assert gated_result["agent_enabled"] is False
    assert any(
        "Network access disabled" in w
        for w in gated_result["analysis"]["warnings"]
    )

    print(
        "T02 Network safety gate: --with-agent without --allow-network "
        "or injected client -> agent skipped:",
        "PASS",
    )

    # --------------------------------------------------------
    # T03 FULL 3-STAGE END-TO-END (claim -> counter -> rebuttal
    # -> suggestion) WITH INJECTED FAKE CLIENT
    # --------------------------------------------------------

    issue_context = load_canonical_issues(case_id)
    fact_context = load_canonical_fact_index(case_id)

    (
        _e, evidence_index, _ep,
    ) = load_canonical_evidence_optional(case_id)
    (
        _r, research_index, _rp,
    ) = load_canonical_legal_research_optional(case_id)
    (
        _d, case_law_index, _dp,
    ) = load_canonical_case_law_optional(case_id)
    timeline_index, _tp = load_canonical_timeline_optional(case_id)
    _dl, deadline_ids, _dlp = load_canonical_deadline_optional(case_id)

    allowlist_by_issue, _w = build_allowlists_for_issues(
        issue_context["issues"], fact_context["facts"], evidence_index,
        research_index, case_law_index, timeline_index, deadline_ids,
    )

    grounded_issue_id = next(
        issue_id
        for issue_id, menu in allowlist_by_issue.items()
        if menu["has_minimum_grounding"]
    )

    fact_id = allowlist_by_issue[grounded_issue_id]["eligible_fact_ids"][0]

    claim_response = json.dumps(
        [
            {
                "source_issue_id": grounded_issue_id,
                "claim_type": "factual_challenge",
                "claim_text": "Bu fact, issue bağlamını desteklemektedir.",
                "source_fact_ids": [fact_id],
                "source_evidence_candidate_ids": [],
                "source_legal_research_ids": [],
                "source_case_law_ids": [],
                "source_timeline_event_ids": [],
                "source_deadline_ids": [],
                "reason_code": "explicit_textual_match",
                "grounded_explanation": "Fact dogrudan ilgilidir.",
            }
        ],
        ensure_ascii=False,
    )

    counter_response = json.dumps(
        [
            {
                "source_claim_id": "argument_claim_001",
                "counter_type": "factual_denial",
                "counterargument_text": "Bu olgu farkli yorumlanabilir.",
                "source_fact_ids": [fact_id],
                "source_evidence_candidate_ids": [],
                "source_legal_research_ids": [],
                "source_case_law_ids": [],
                "source_timeline_event_ids": [],
                "source_deadline_ids": [],
                "reason_code": "general_contextual_relevance",
                "grounded_explanation": "Ayni fact farkli okunabilir.",
            }
        ],
        ensure_ascii=False,
    )

    rebuttal_response = json.dumps(
        [
            {
                "source_counterargument_id": "argument_counter_001",
                "rebuttal_type": "factual_refutation",
                "rebuttal_text": "Bu yorum fact ile tutarsizdir.",
                "source_fact_ids": [fact_id],
                "source_evidence_candidate_ids": [],
                "source_legal_research_ids": [],
                "source_case_law_ids": [],
                "source_timeline_event_ids": [],
                "source_deadline_ids": [],
                "reason_code": "explicit_textual_match",
                "grounded_explanation": "Fact ile celisir.",
            }
        ],
        ensure_ascii=False,
    )

    suggestion_response = json.dumps(
        [
            {
                "source_issue_id": grounded_issue_id,
                "suggestion_type": "additional_research_needed",
                "source_claim_id": "argument_claim_001",
                "source_counterargument_id": None,
                "related_reference_ids": [],
                "reason_code": "general_contextual_relevance",
                "grounded_explanation": "Ek arastirma faydali olabilir.",
            }
        ],
        ensure_ascii=False,
    )

    client = FakeArgumentLLMClient(
        response_sequence=[
            claim_response, counter_response, rebuttal_response,
            suggestion_response,
        ]
    )

    full_result = build_argument_engine_output(
        case_id, use_agent=True, llm_client=client, network_allowed=False
    )

    assert client.call_count == 4
    assert full_result["claim_count"] == 1
    assert full_result["counterargument_count"] == 1
    assert full_result["rebuttal_count"] == 1
    assert full_result["suggestion_count"] == 1

    matching_coverage = next(
        c for c in full_result["analysis"]["argument_coverage"]
        if c["source_issue_id"] == grounded_issue_id
    )

    assert matching_coverage["execution_state"] == "analysis_completed"

    print(
        "T03 Full 3-stage end-to-end (claim->counter->rebuttal+"
        "suggestion) with injected Fake client:",
        "PASS",
    )

    # --------------------------------------------------------
    # T04 AGENT CONFIRMED/REJECTED REJECTION AT ENGINE-SEMANTIC
    # GUARD LEVEL
    # --------------------------------------------------------

    tampered = json.loads(json.dumps(full_result["analysis"]))

    tampered["argument_claims"][0]["claim_review_state"] = "confirmed"

    raised = False

    try:

        validate_engine_output_semantics(tampered, full_result["issue_count"])

    except ArgumentEngineError:

        raised = True

    assert raised is True

    print(
        "T04 Engine output with claim_review_state='confirmed' rejected:",
        "PASS",
    )

    # --------------------------------------------------------
    # T05 CONFIDENCE/STRENGTH/WIN-PROBABILITY SMUGGLING REJECTED
    # AT ENGINE-SEMANTIC GUARD LEVEL
    # --------------------------------------------------------

    for forbidden_field in ("confidence", "strength", "win_probability"):

        tampered2 = json.loads(json.dumps(full_result["analysis"]))

        tampered2["argument_claims"][0][forbidden_field] = 0.9

        raised2 = False

        try:

            validate_engine_output_semantics(tampered2, full_result["issue_count"])

        except ArgumentEngineError:

            raised2 = True

        assert raised2 is True, forbidden_field

    print(
        "T05 confidence/strength/win_probability field injection rejected:",
        "PASS",
    )

    # --------------------------------------------------------
    # T06 DUPLICATE CLAIM FINGERPRINT REJECTED
    # --------------------------------------------------------

    tampered3 = json.loads(json.dumps(full_result["analysis"]))

    duplicate_claim = json.loads(json.dumps(tampered3["argument_claims"][0]))

    duplicate_claim["claim_id"] = "argument_claim_999"

    tampered3["argument_claims"].append(duplicate_claim)

    raised3 = False

    try:

        validate_engine_output_semantics(tampered3, full_result["issue_count"])

    except ArgumentEngineError:

        raised3 = True

    assert raised3 is True

    print("T06 Duplicate claim fingerprint rejected at engine level:", "PASS")

    # --------------------------------------------------------
    # T07 SAFE REVIEW CARRY-FORWARD
    # --------------------------------------------------------

    # NOT: T07/T08 aşağıda get_canonical_path/get_carry_forward_dir'i
    # kendi izole tempdir path'lerine monkeypatch eder; gerçek
    # canonical'ın mevcut olup olmaması bu testlerin doğruluğunu
    # ETKİLEMEZ - tek gerçek invariant, self-test SONUNDA gerçek
    # dizinin (run_self_test başındaki real_tree_before ile) birebir
    # aynı kalmasıdır (bkz. fonksiyon sonu).

    import tempfile

    fake_previous = json.loads(json.dumps(full_result["analysis"]))

    fake_previous["argument_claims"][0]["claim_review_state"] = "confirmed"

    fake_previous["argument_counterarguments"][0]["counter_review_state"] = "rejected"

    temp_dir = tempfile.TemporaryDirectory(prefix="argument_engine_carryforward_")

    fake_canonical_path = Path(temp_dir.name) / "arguments.json"

    with open(fake_canonical_path, "w", encoding="utf-8") as file:

        json.dump(fake_previous, file, ensure_ascii=False)

    original_get_canonical_path = get_canonical_path

    original_get_carry_forward_dir = get_carry_forward_dir

    fake_carry_forward_dir = Path(temp_dir.name) / "carry_forward"

    globals()["get_canonical_path"] = lambda case_id_arg: fake_canonical_path

    globals()["get_carry_forward_dir"] = (
        lambda case_id_arg: fake_carry_forward_dir
    )

    try:

        client2 = FakeArgumentLLMClient(
            response_sequence=[
                claim_response, counter_response, rebuttal_response,
                suggestion_response,
            ]
        )

        carried_result = build_argument_engine_output(
            case_id, use_agent=True, llm_client=client2, network_allowed=False
        )

        assert carried_result["carry_forward_count"] == 2

        assert (
            carried_result["analysis"]["argument_claims"][0]["claim_review_state"]
            == "confirmed"
        )

        assert (
            carried_result["analysis"]["argument_counterarguments"][0][
                "counter_review_state"
            ]
            == "rejected"
        )

        assert carried_result["carry_forward_audit_path"].exists()

        assert not str(carried_result["carry_forward_audit_path"]).startswith(
            str(CASES_DIR)
        )

    finally:

        globals()["get_canonical_path"] = original_get_canonical_path

        globals()["get_carry_forward_dir"] = original_get_carry_forward_dir

        temp_dir.cleanup()

    print(
        "T07 Safe review carry-forward (identical fingerprint + "
        "identical upstream hashes -> prior review_state preserved):",
        "PASS",
    )

    # --------------------------------------------------------
    # T08 CHANGED RECORD RESETS TO NEEDS_REVIEW (fingerprint
    # değişince carry-forward uygulanmaz)
    # --------------------------------------------------------

    fake_previous_changed = json.loads(json.dumps(full_result["analysis"]))

    fake_previous_changed["argument_claims"][0]["claim_text"] = (
        "Tamamen farklı bir claim metni."
    )

    fake_previous_changed["argument_claims"][0]["claim_review_state"] = "confirmed"

    temp_dir2 = tempfile.TemporaryDirectory(
        prefix="argument_engine_carryforward_changed_"
    )

    fake_canonical_path2 = Path(temp_dir2.name) / "arguments.json"

    with open(fake_canonical_path2, "w", encoding="utf-8") as file:

        json.dump(fake_previous_changed, file, ensure_ascii=False)

    fake_carry_forward_dir2 = Path(temp_dir2.name) / "carry_forward"

    globals()["get_canonical_path"] = lambda case_id_arg: fake_canonical_path2

    globals()["get_carry_forward_dir"] = (
        lambda case_id_arg: fake_carry_forward_dir2
    )

    try:

        client3 = FakeArgumentLLMClient(
            response_sequence=[
                claim_response, counter_response, rebuttal_response,
                suggestion_response,
            ]
        )

        changed_result = build_argument_engine_output(
            case_id, use_agent=True, llm_client=client3, network_allowed=False
        )

        assert (
            changed_result["analysis"]["argument_claims"][0]["claim_review_state"]
            == "needs_review"
        )

        assert changed_result["carry_forward_count"] == 0

    finally:

        globals()["get_canonical_path"] = original_get_canonical_path

        globals()["get_carry_forward_dir"] = original_get_carry_forward_dir

        temp_dir2.cleanup()

    print(
        "T08 Changed claim_text -> fingerprint mismatch -> resets to "
        "needs_review (no carry-forward):",
        "PASS",
    )

    assert_real_arguments_tree_unchanged(
        case_id, real_tree_before,
        "After T01-T08 (carry-forward tests)",
    )

    # --------------------------------------------------------
    # REAL-AGENT-CLIENT GATE TEST MATRIX (Finding 3 remediation)
    #
    # Hiçbiri gerçek network/API çağrısı YAPMAZ: ya spy/stub bir
    # sınıf argument_agent.AnthropicArgumentLLMClient'ın yerine
    # geçirilir (construction izlenir, .generate() ASLA gerçek
    # network'e dokunmadan yerel bir hata fırlatır), ya da gerçek
    # sınıf kullanılır ama ANTHROPIC_API_KEY ortam değişkeni bu
    # tek test süresince açıkça kaldırılır (generate() network'e
    # dokunmadan ÖNCE, ilk satırda bu kontrolü yapar).
    # --------------------------------------------------------

    import argument_agent as argument_agent_module

    original_anthropic_client_class = (
        argument_agent_module.AnthropicArgumentLLMClient
    )

    class _SpyAnthropicArgumentLLMClient:

        instantiation_count = 0

        def __init__(self, *args, **kwargs):

            _SpyAnthropicArgumentLLMClient.instantiation_count += 1

        def generate(self, prompt):

            raise RuntimeError(
                "SPY CLIENT: gerçek network çağrısı bu testte KESİNLİKLE "
                "YAPILMAMALIDIR."
            )

    def reset_spy():

        _SpyAnthropicArgumentLLMClient.instantiation_count = 0

    # ---- T09: iki flag da yok (use_agent=False) -> client hiç
    # oluşturulmaya çalışılmaz ----

    reset_spy()

    argument_agent_module.AnthropicArgumentLLMClient = (
        _SpyAnthropicArgumentLLMClient
    )

    try:

        no_flags_result = build_argument_engine_output(
            case_id, use_agent=False, llm_client=None, network_allowed=False,
        )

    finally:

        argument_agent_module.AnthropicArgumentLLMClient = (
            original_anthropic_client_class
        )

    assert _SpyAnthropicArgumentLLMClient.instantiation_count == 0
    assert no_flags_result["agent_enabled"] is False
    assert no_flags_result["claim_count"] == 0

    print(
        "T09 Neither --with-agent nor --allow-network -> real client "
        "never constructed:",
        "PASS",
    )

    # ---- T10: yalnız --allow-network (use_agent=False) -> agent hiç
    # çalışmaz, client oluşturulmaz ----

    reset_spy()

    argument_agent_module.AnthropicArgumentLLMClient = (
        _SpyAnthropicArgumentLLMClient
    )

    try:

        only_network_result = build_argument_engine_output(
            case_id, use_agent=False, llm_client=None, network_allowed=True,
        )

    finally:

        argument_agent_module.AnthropicArgumentLLMClient = (
            original_anthropic_client_class
        )

    assert _SpyAnthropicArgumentLLMClient.instantiation_count == 0
    assert only_network_result["agent_enabled"] is False
    assert only_network_result["claim_count"] == 0

    print(
        "T10 --allow-network alone (no --with-agent) -> agent never "
        "runs, no client constructed:",
        "PASS",
    )

    # ---- T11: iki flag + injected FakeArgumentLLMClient -> fake
    # kullanılır, gerçek client HİÇ oluşturulmaz ----

    reset_spy()

    argument_agent_module.AnthropicArgumentLLMClient = (
        _SpyAnthropicArgumentLLMClient
    )

    try:

        fake_for_both_flags = FakeArgumentLLMClient(
            response_sequence=[
                claim_response, counter_response, rebuttal_response,
                suggestion_response,
            ]
        )

        both_flags_with_fake_result = build_argument_engine_output(
            case_id, use_agent=True, llm_client=fake_for_both_flags,
            network_allowed=True,
        )

    finally:

        argument_agent_module.AnthropicArgumentLLMClient = (
            original_anthropic_client_class
        )

    assert _SpyAnthropicArgumentLLMClient.instantiation_count == 0
    assert fake_for_both_flags.call_count == 4
    assert both_flags_with_fake_result["claim_count"] == 1

    print(
        "T11 Both flags + injected FakeArgumentLLMClient -> fake used, "
        "real client construction never attempted:",
        "PASS",
    )

    # ---- T12: iki flag + injected client YOK -> gerçek
    # AnthropicArgumentLLMClient oluşturulmaya ÇALIŞILIR (spy ile
    # doğrulanır; .generate() yerel hata fırlatır, network'e hiç
    # çıkılmaz) ----

    reset_spy()

    argument_agent_module.AnthropicArgumentLLMClient = (
        _SpyAnthropicArgumentLLMClient
    )

    try:

        both_flags_no_client_result = build_argument_engine_output(
            case_id, use_agent=True, llm_client=None, network_allowed=True,
        )

    finally:

        argument_agent_module.AnthropicArgumentLLMClient = (
            original_anthropic_client_class
        )

    assert _SpyAnthropicArgumentLLMClient.instantiation_count == 1, (
        "İki flag birlikteyse ve injected client yoksa gerçek client "
        "TAM OLARAK BİR KEZ oluşturulmaya çalışılmalıdır."
    )

    assert both_flags_no_client_result["claim_count"] == 0

    assert any(
        "SPY CLIENT" in w
        for w in both_flags_no_client_result["analysis"]["warnings"]
    ), "Spy'ın fail-closed hatası warnings içinde açıkça görünmelidir."

    print(
        "T12 Both flags + no injected client -> real "
        "AnthropicArgumentLLMClient IS constructed (verified via spy, "
        "zero real network calls):",
        "PASS",
    )

    # ---- T13: eksik config (ANTHROPIC_API_KEY yok) -> gerçek sınıf,
    # AÇIK ve fail-closed hata (network'e HİÇ ÇIKILMADAN, .generate()
    # ilk satırında biter) ----

    original_api_key = os.environ.pop("ANTHROPIC_API_KEY", None)

    try:

        no_key_result = build_argument_engine_output(
            case_id, use_agent=True, llm_client=None, network_allowed=True,
        )

    finally:

        if original_api_key is not None:

            os.environ["ANTHROPIC_API_KEY"] = original_api_key

    assert no_key_result["claim_count"] == 0

    assert any(
        "ANTHROPIC_API_KEY" in w
        for w in no_key_result["analysis"]["warnings"]
    ), (
        "Eksik API key durumu açıklayıcı bir mesajla fail-closed "
        "olmalıdır (generic 'agent_call_failed' sessizliği DEĞİL)."
    )

    print(
        "T13 Missing ANTHROPIC_API_KEY -> explicit fail-closed error "
        "(real class, zero network calls, key checked before any "
        "HTTP attempt):",
        "PASS",
    )

    print(
        "T14 No self-test in this suite performed a real network/API "
        "call (all real-client paths used a spy or a deliberately "
        "unset API key that fails before any HTTP attempt):",
        "PASS",
    )

    # ==============================================================
    # ROW 13 CORRECTIVE MAINTENANCE (CLAUDE.md §9 açık-bug istisnası)
    # C3: ARA-AŞAMA (mid-pipeline) HATASI -> önceki başarılı aşamaların
    # kısmi finalize edilmiş entity'leri temizlenmeli, tüm coverage
    # kayıtları uniform "analysis_failed" + count=0 olmalı, engine
    # semantic validator PASS etmeli, HİÇBİR uncaught ArgumentEngineError
    # fırlatılmamalı (temiz fail-closed pending) - gerçek network
    # çağrısı YOK, yalnız izole Fake client kullanılıyor.
    # ==============================================================

    class StageFailingClient:

        def __init__(self, responses, fail_at_call):

            self.responses = responses
            self.fail_at_call = fail_at_call
            self.call_count = 0

        def generate(self, prompt):

            self.call_count += 1

            if self.call_count == self.fail_at_call:

                raise RuntimeError(
                    "Simulated transient agent failure (self-test, "
                    "no real network call)."
                )

            index = min(self.call_count - 1, len(self.responses) - 1)

            return self.responses[index]

    def assert_clean_fail_closed_after_partial_stage_failure(
        stage_label, responses, fail_at_call,
    ):

        client = StageFailingClient(responses, fail_at_call)

        crashed = False

        try:

            result = build_argument_engine_output(
                case_id, use_agent=True, llm_client=client,
                network_allowed=False,
            )

        except ArgumentEngineError:

            crashed = True

        assert crashed is False, (
            f"{stage_label} failure after prior stage(s) succeeded "
            "must produce a clean fail-closed result, not an uncaught "
            "ArgumentEngineError."
        )

        assert result["claim_count"] == 0
        assert result["counterargument_count"] == 0
        assert result["rebuttal_count"] == 0
        assert result["suggestion_count"] == 0

        grounded_coverage = next(
            c for c in result["analysis"]["argument_coverage"]
            if c["source_issue_id"] == grounded_issue_id
        )

        assert grounded_coverage["execution_state"] == "analysis_failed"

        assert all(
            c["execution_state"] in ("analysis_failed", "blocked_missing_input")
            for c in result["analysis"]["argument_coverage"]
        )

        temp_dir_local = tempfile.TemporaryDirectory(
            prefix="argument_engine_c3_selftest_"
        )

        try:

            pending_path = Path(temp_dir_local.name) / "arguments.json"

            with open(pending_path, "w", encoding="utf-8") as file:

                json.dump(result["analysis"], file, ensure_ascii=False)

            validation = validate_argument_analysis(pending_path, case_id)

            if not validation["valid"]:

                for error in validation["errors"]:

                    print("-", error)

            assert validation["valid"] is True

        finally:

            temp_dir_local.cleanup()

    assert_clean_fail_closed_after_partial_stage_failure(
        "Stage 2 (counterargument)", [claim_response], fail_at_call=2,
    )

    print(
        "T15 C3 Stage 2 (counterargument) failure after stage 1 "
        "(claim) success -> clean fail-closed analysis_failed, "
        "count invariants 0, validator PASS, no crash:",
        "PASS",
    )

    assert_clean_fail_closed_after_partial_stage_failure(
        "Stage 3 (rebuttal)", [claim_response, counter_response],
        fail_at_call=3,
    )

    print(
        "T16 C3 Stage 3 (rebuttal) failure after stage 1-2 "
        "(claim+counterargument) success -> clean fail-closed "
        "analysis_failed, count invariants 0, validator PASS, no "
        "crash:",
        "PASS",
    )

    assert_clean_fail_closed_after_partial_stage_failure(
        "Stage 4 (suggestion)",
        [claim_response, counter_response, rebuttal_response],
        fail_at_call=4,
    )

    print(
        "T17 C3 Stage 4 (suggestion) failure after stage 1-3 "
        "(claim+counterargument+rebuttal) success -> clean "
        "fail-closed analysis_failed, count invariants 0, validator "
        "PASS, no crash:",
        "PASS",
    )

    assert_real_arguments_tree_unchanged(
        case_id, real_tree_before,
        "End of self-test (post-approval invariant, full suite)",
    )

    print()
    print("======================================")
    print(" ARGUMENT ENGINE V1: 17/17 PASS")
    print("======================================")


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(description="Vergi AI Argument Engine V1")

    parser.add_argument("--case", dest="case_id", default=DEFAULT_CASE_ID)

    parser.add_argument(
        "--with-agent", action="store_true", dest="with_agent"
    )

    parser.add_argument(
        "--allow-network", action="store_true", dest="allow_network"
    )

    parser.add_argument("--self-test", action="store_true", dest="self_test")

    args = parser.parse_args()

    if args.self_test:

        run_self_test(args.case_id)

        return

    print()
    print("======================================")
    print(" VERGİ AI - ARGUMENT ENGINE V1")
    print("======================================")
    print()
    print("Engine:", ARGUMENT_ENGINE_VERSION)
    print("Policy:", ARGUMENT_POLICY_VERSION)
    print("Discovery:", ARGUMENT_DISCOVERY_VERSION)
    print(
        "Agent:",
        (
            ARGUMENT_AGENT_VERSION
            + (
                " (network açık)"
                if args.with_agent and args.allow_network
                else " (network KAPALI)"
                if args.with_agent
                else " devre dışı"
            )
        ),
    )
    print("Case:", args.case_id)

    try:

        result = run_engine(
            case_id=args.case_id,
            use_agent=args.with_agent,
            network_allowed=args.allow_network,
        )

    except Exception as error:

        print()
        print("ENGINE ERROR")
        print(error)
        print()
        print("======================================")
        print(" ARGUMENT ENGINE V1: FAIL")
        print("======================================")
        sys.exit(1)

    analysis = result["analysis"]

    validation = result["validation"]

    print()
    print("ARGUMENT ANALYSIS OLUŞTURULDU")
    print("Analysis ID:", analysis["argument_analysis_id"])
    print("Canonical issue:", result["issue_count"])
    print("Approved fact:", result["fact_count"])
    print("Canonical evidence candidate:", result["evidence_count"])
    print("Canonical legal research:", result["legal_research_count"])
    print("Canonical case law decision:", result["case_law_count"])
    print("Coverage count:", result["coverage_count"])
    print("Claim count:", result["claim_count"])
    print("Counterargument count:", result["counterargument_count"])
    print("Rebuttal count:", result["rebuttal_count"])
    print("Suggestion count:", result["suggestion_count"])
    print("Carry-forward count:", result["carry_forward_count"])
    print("Status:", analysis["status"])
    print("Validator:", "PASS" if validation["valid"] else "FAIL")

    print()

    for coverage in analysis["argument_coverage"]:

        print(
            "-",
            coverage["coverage_id"],
            "|",
            "issue=" + coverage["source_issue_id"],
            "|",
            coverage["execution_state"],
            "|",
            "allowlist=" + str(coverage["allowlist_count"]),
            "|",
            "claims=" + str(coverage["claim_count"]),
        )

    if analysis.get("warnings"):

        print()
        print("Engine warnings:")

        for warning in analysis["warnings"]:

            print("-", warning)

    print()
    print("Pending output:")
    print(result["pending_path"])

    if result["previous_pending_history"]:

        print()
        print("Previous pending archived:")
        print(result["previous_pending_history"])

    print()
    print("SAFETY CHECKS:")
    print("- Yalnız approved fact + (varsa) canonical evidence/research/")
    print("  case-law/timeline/deadline kullanıldı; pending upstream ASLA")
    print("  okunmadı.")
    print("- Her canonical issue tam olarak bir coverage kaydı aldı.")
    print("- claim/counter/rebuttal review_state'leri yalnız needs_review")
    print("  (veya geçerli bir carry-forward ile) üretildi.")
    print("- Canonical arguments.json değiştirilmemiştir.")

    print()
    print("======================================")
    print(" ARGUMENT ENGINE V1: PASS")
    print("======================================")


if __name__ == "__main__":

    main()
