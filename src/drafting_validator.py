# ============================================================
# VERGİ AI - DRAFTING VALIDATOR V1
#
# AMAÇ: Row 15 pending/canonical taslak analizini AGENT'A GÜVENMEDEN,
# bağımsız olarak yeniden doğrulamak. Bu modül agent'ın yüksek
# seviyeli check_text_safety() sarmalayıcısını ASLA import etmez -
# yalnız drafting_policy.py'nin paylaşılan, saf, düşük seviyeli
# fonksiyonlarını kullanır (Row 13/14'ün defense-in-depth deseni).
# ============================================================

import argparse
import json

from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from legal_research_validator import load_canonical_issues
from timeline_validator import load_canonical_fact_index

from argument_discovery import (
    load_canonical_evidence_optional,
    load_canonical_legal_research_optional,
    load_canonical_case_law_optional,
    load_canonical_timeline_optional,
    load_canonical_deadline_optional,
)

from risk_strategy_discovery import load_canonical_arguments_optional

from drafting_discovery import (
    build_active_documents_index,
    build_allowlists_for_issues,
    load_canonical_risk_strategy_optional,
    compute_selection_scope,
    legal_research_grounding_class,
)

from drafting_policy import (
    DRAFT_INTENT_TYPES,
    APPEAL_LEVELS,
    SELECTION_SCOPES,
    EXECUTION_STATES,
    ZERO_SECTION_EXECUTION_STATES,
    BLOCK_REASONS,
    REF_FIELDS,
    SECTION_TYPES,
    RENDERING_MODES,
    sha256_of,
    compute_lawyer_input_hash,
    compute_section_dedup_fingerprint,
    render_gap_note,
    render_disputed_content_note,
    render_agent_suggested_citation_note,
    render_needs_review_flagged_note,
    check_forbidden_phrases_context,
    find_id_reference_issues,
    find_unverified_quotes,
    find_unsupported_numeric_tokens,
    find_refs_missing_hedge,
    is_ref_direct,
    compute_request_authorization,
    is_valid_request_input,
    has_valid_lawyer_text,
    collect_citable_texts,
    NOTE_TYPES,
)


DRAFTING_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "data" / "case_drafting.schema.json"

DEFAULT_CASE_ID = "case_0001"


def load_json(path):

    with open(path, "r", encoding="utf-8") as file:

        return json.load(file)


# ============================================================
# SCHEMA / IDENTITY
# ============================================================

def validate_schema(analysis):

    schema = load_json(DRAFTING_SCHEMA_PATH)

    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    return [f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in validator.iter_errors(analysis)]


def validate_case_id(analysis, expected_case_id):

    errors = []

    if analysis.get("case_id") != expected_case_id:

        errors.append(f"case_id uyuşmuyor: beklenen={expected_case_id}, kayıtlı={analysis.get('case_id')}")

    return errors


def validate_generated_at(analysis):

    errors = []

    if not isinstance(analysis.get("generated_at"), str) or not analysis["generated_at"]:

        errors.append("generated_at eksik/geçersiz.")

    return errors


# ============================================================
# ANALYSIS METADATA (10 canonical hash + lawyer_input_hash)
# ============================================================

def validate_analysis_metadata(analysis_metadata, current_hashes):

    errors = []

    def check(field, recorded, current, exists):

        if not exists:

            if recorded is not None:

                errors.append(f"analysis_metadata.{field}: kaynak yok ama hash null değil.")

            return

        if recorded is None:

            errors.append(f"analysis_metadata.{field}: kaynak var ama hash null.")

            return

        if recorded != current:

            errors.append(f"STALE analysis_metadata.{field}: kayıtlı hash güncel canonical veriyle eşleşmiyor.")

    for field, (recorded, current, exists) in current_hashes.items():

        check(field, recorded, current, exists)

    lawyer_input = analysis_metadata.get("lawyer_input", {})

    recomputed_lawyer_hash = compute_lawyer_input_hash(lawyer_input)

    if recomputed_lawyer_hash != analysis_metadata.get("lawyer_input_hash"):

        errors.append(
            "lawyer_input_hash bağımsız yeniden hesaplamayla eşleşmiyor "
            "(kayıtlı lawyer_input alanından tutarsız/tamper şüphesi)."
        )

    draft_intent_type = lawyer_input.get("draft_intent_type")

    if draft_intent_type is not None and draft_intent_type not in DRAFT_INTENT_TYPES:

        errors.append(f"Geçersiz draft_intent_type: {draft_intent_type}")

    appeal_level = lawyer_input.get("appeal_level")

    if draft_intent_type == "appeal_petition" and appeal_level not in APPEAL_LEVELS:

        errors.append("appeal_petition için appeal_level açıkça sağlanmalıdır (istinaf|temyiz).")

    if draft_intent_type != "appeal_petition" and appeal_level is not None:

        errors.append("appeal_level yalnız appeal_petition için doldurulabilir.")

    return errors


# ============================================================
# DRAFT COVERAGE
# ============================================================

def validate_draft_coverage(coverage_records, issue_index, allowlist_by_issue, selected_issue_ids, sections):

    errors = []

    produced_by_issue = {}

    for section in sections:

        for issue_id in section.get("source_issue_ids", []):

            produced_by_issue[issue_id] = produced_by_issue.get(issue_id, 0) + 1

    covered_issue_ids = set()

    for coverage in coverage_records:

        coverage_id = coverage.get("coverage_id")

        issue_id = coverage.get("source_issue_id")

        if issue_id not in issue_index:

            errors.append(f"{coverage_id}: source_issue_id bilinmeyen: {issue_id}")

            continue

        covered_issue_ids.add(issue_id)

        expected_scope = compute_selection_scope(issue_id, selected_issue_ids)

        if coverage.get("selection_scope") != expected_scope:

            errors.append(
                f"{coverage_id}: selection_scope bağımsız yeniden hesaplamayla "
                f"eşleşmiyor (beklenen={expected_scope}, kayıtlı={coverage.get('selection_scope')})."
            )

        menu = allowlist_by_issue.get(issue_id, {})

        expected_allowlist_count = menu.get("allowlist_count", 0)

        if coverage.get("allowlist_count") != expected_allowlist_count:

            errors.append(
                f"{coverage_id}: allowlist_count yanlış (bağımsız={expected_allowlist_count}, "
                f"kayıtlı={coverage.get('allowlist_count')})."
            )

        expected_produced = produced_by_issue.get(issue_id, 0)

        if coverage.get("produced_section_count") != expected_produced:

            errors.append(
                f"{coverage_id}: produced_section_count yanlış (bağımsız={expected_produced}, "
                f"kayıtlı={coverage.get('produced_section_count')})."
            )

        execution_state = coverage.get("execution_state")

        if execution_state not in EXECUTION_STATES:

            errors.append(f"{coverage_id}: geçersiz execution_state: {execution_state}")

        if execution_state in ZERO_SECTION_EXECUTION_STATES and coverage.get("produced_section_count") != 0:

            errors.append(
                f"{coverage_id}: execution_state={execution_state} iken "
                "produced_section_count 0 olmalıdır."
            )

        block_reason = coverage.get("block_reason")

        if block_reason is not None and block_reason not in BLOCK_REASONS:

            errors.append(f"{coverage_id}: geçersiz block_reason: {block_reason}")

        if expected_scope == "selection_not_provided" and block_reason != "blocked_missing_lawyer_input":

            errors.append(
                f"{coverage_id}: selection_not_provided iken block_reason="
                "'blocked_missing_lawyer_input' olmalıdır (yalnız 'selected' "
                "kayıtlarla sınırlanamaz)."
            )

    if len(coverage_records) != len(issue_index) or covered_issue_ids != set(issue_index.keys()):

        errors.append("Her canonical issue tam olarak bir draft_coverage kaydına sahip olmalıdır.")

    return errors


# ============================================================
# DRAFT SOURCE REFS (allowlist + rejected-ata + cross-issue + rendering)
# ============================================================

def validate_draft_source_refs(refs, sections, allowlist_by_issue):

    errors = []

    section_by_id = {s["section_id"]: s for s in sections}

    for ref in refs:

        section = section_by_id.get(ref.get("section_id"))

        if section is None:

            errors.append(f"{ref.get('source_ref_id')}: bilinmeyen section_id: {ref.get('section_id')}")

            continue

        source_field = ref.get("source_field")

        if source_field not in REF_FIELDS:

            errors.append(f"{ref.get('source_ref_id')}: geçersiz source_field: {source_field}")

            continue

        rendering_mode = ref.get("rendering_mode")

        if rendering_mode not in RENDERING_MODES:

            errors.append(f"{ref.get('source_ref_id')}: geçersiz rendering_mode: {rendering_mode}")

        if rendering_mode == "direct_quote" and source_field != "source_fact_ids":

            errors.append(
                f"{ref.get('source_ref_id')}: direct_quote yalnız source_fact_ids "
                "için izinlidir (mevzuat/içtihat tam metni yok)."
            )

        field_key = {
            "source_fact_ids": "eligible_fact_ids",
            "source_timeline_event_ids": "eligible_timeline_event_ids",
            "source_deadline_ids": "eligible_deadline_ids",
            "source_legal_research_ids": "eligible_legal_research_ids",
            "source_case_law_ids": "eligible_case_law_ids",
            "source_evidence_candidate_ids": "eligible_evidence_candidate_ids",
            "source_claim_ids": "eligible_claim_ids",
            "source_counterargument_ids": "eligible_counterargument_ids",
            "source_rebuttal_ids": "eligible_rebuttal_ids",
            "source_risk_ids": "eligible_risk_ids",
            "source_strategy_ids": "eligible_strategy_ids",
        }[source_field]

        allowed_across_issues = set()

        for issue_id in section.get("source_issue_ids", []):

            menu = allowlist_by_issue.get(issue_id, {})

            allowed_across_issues |= set(menu.get(field_key, []))

        if ref.get("source_id") not in allowed_across_issues:

            errors.append(
                f"{ref.get('source_ref_id')}: allowlist dışı/cross-issue referans "
                f"({source_field}): {ref.get('source_id')}"
            )

    return errors


# ============================================================
# DRAFT SECTIONS (bağımsız text-safety + contains_unreviewed_source + request authority)
# ============================================================

def validate_draft_sections(
    sections, refs, allowlist_by_issue, fact_index, all_known_ids, lawyer_provided_text,
    request_input=None, direct_lookup=None,
):

    direct_lookup = direct_lookup or {}

    errors = []

    refs_by_section = {}

    for ref in refs:

        refs_by_section.setdefault(ref["section_id"], []).append(ref)

    seen_fingerprints = set()

    for section in sections:

        section_id = section.get("section_id")

        section_type = section.get("section_type")

        if section_type not in SECTION_TYPES:

            errors.append(f"{section_id}: geçersiz section_type: {section_type}")

            continue

        section_refs = refs_by_section.get(section_id, [])

        if not section_refs:

            errors.append(f"{section_id}: en az bir kaynak referansı (draft_source_refs) zorunludur.")

            continue

        declared_ids = {r["source_id"] for r in section_refs}

        fact_ids_in_refs = [r["source_id"] for r in section_refs if r["source_field"] == "source_fact_ids"]

        citable_texts = collect_citable_texts(fact_index, fact_ids_in_refs)

        # ---- Q1 (dayanak) vs Q2 (avukat ÜRETİMİ istedi mi) - AYRI ----

        is_grounded_advocacy = (
            has_valid_lawyer_text(lawyer_provided_text)
            or is_valid_request_input(request_input)
            or any(
                r["source_field"] in ("source_claim_ids", "source_counterargument_ids", "source_rebuttal_ids")
                for r in section_refs
            )
        )

        request_authorized = compute_request_authorization(request_input, lawyer_provided_text)

        text = section.get("section_text")

        forbidden_errors = check_forbidden_phrases_context(section_id, text, section_type, is_grounded_advocacy)

        errors.extend(forbidden_errors)

        id_issues = find_id_reference_issues(text, declared_ids, all_known_ids)

        if id_issues["fabricated"]:

            errors.append(f"{section_id}: canonical'da hiç var olmayan, uydurma ID içeriyor: {id_issues['fabricated']}")

        if id_issues["smuggled"]:

            errors.append(
                f"{section_id}: gerçek ama başka issue'ya ait veya beyan edilmemiş ID içeriyor: {id_issues['smuggled']}"
            )

        unverified_quotes = find_unverified_quotes(text, citable_texts)

        if unverified_quotes:

            errors.append(f"{section_id}: doğrulanamayan alıntı içeriyor: {unverified_quotes}")

        unsupported = find_unsupported_numeric_tokens(text, citable_texts)

        if unsupported:

            errors.append(f"{section_id}: desteklenmeyen tarih/tutar/süre/yıl içeriyor: {unsupported}")

        if section_type == "request" and not request_authorized:

            errors.append(
                f"{section_id}: 'request' section'ı avukatın AÇIK ÜRETİM yetkisi "
                "(request_input veya lawyer_provided_text) olmadan üretilemez - "
                "confirmed argüman/risk/strateji tek başına yeterli değildir."
            )

        # ---- BAĞIMSIZ contains_unreviewed_source YENİDEN HESAPLAMASI +
        # HER flagged ref için hedge-span kontrolü (madde F/C) ----

        recomputed_flagged = [
            r for r in section_refs if not is_ref_direct(r, section.get("source_issue_ids", []), direct_lookup)
        ]

        expected_contains_unreviewed = bool(recomputed_flagged)

        if section.get("contains_unreviewed_source") != expected_contains_unreviewed:

            errors.append(
                f"{section_id}: contains_unreviewed_source bağımsız yeniden hesaplamayla "
                f"eşleşmiyor (beklenen={expected_contains_unreviewed}, "
                f"kayıtlı={section.get('contains_unreviewed_source')})."
            )

        if recomputed_flagged:

            missing_hedge = find_refs_missing_hedge(text, recomputed_flagged)

            if missing_hedge:

                errors.append(
                    f"{section_id}: flagged kaynak(lar) için claim_span içinde "
                    f"belirsizlik ifadesi eksik/geçersiz: {missing_hedge}"
                )

        if section.get("submission_status") != "draft_only":

            errors.append(f"{section_id}: submission_status='draft_only' olmalıdır.")

        ref_field_id_pairs = [(r["source_field"], r["source_id"]) for r in section_refs]

        fp = compute_section_dedup_fingerprint(section, ref_field_id_pairs)

        if fp in seen_fingerprints:

            errors.append(f"{section_id}: duplicate section (fingerprint çakışması).")

        seen_fingerprints.add(fp)

    return errors


# ============================================================
# DRAFT REVIEW NOTES (deterministik gap-note template eşitliği)
# ============================================================

def validate_draft_review_notes(review_notes, coverage_records, allowlist_by_issue, sections, refs, direct_lookup):

    errors = []

    coverage_by_issue = {c["source_issue_id"]: c for c in coverage_records}

    # ---- Bağımsız TAMLIK kontrolü: her not türü için BEKLENEN kümeyi
    # kendi kaynağından (coverage/menu/sections) yeniden hesapla ve
    # kayıtlı notlarla TAM eşleştiğini doğrula (ne eksik ne fazla). ----

    expected_gap_ids = set()

    expected_disputed_ids = set()

    expected_agent_suggested_ids = set()

    for issue_id, coverage in coverage_by_issue.items():

        if coverage.get("block_reason") is not None and coverage.get("execution_state") != "analysis_not_run":

            expected_gap_ids.add(f"drafting_gap_note_{issue_id}")

        menu = allowlist_by_issue.get(issue_id, {})

        for denied_event in menu.get("denied_timeline_events", []):

            expected_disputed_ids.add(f"drafting_disputed_content_{issue_id}_{denied_event['source_id']}")

        for research_id in menu.get("agent_suggested_research_ids", []):

            expected_agent_suggested_ids.add(
                f"drafting_agent_suggested_citation_only_{issue_id}_{research_id}"
            )

    expected_flagged_ids = set()

    refs_by_section = {}

    for ref in refs:

        refs_by_section.setdefault(ref["section_id"], []).append(ref)

    for section in sections:

        section_refs = refs_by_section.get(section["section_id"], [])

        for ref in section_refs:

            if not is_ref_direct(ref, section.get("source_issue_ids", []), direct_lookup):

                expected_flagged_ids.add(f"drafting_needs_review_flagged_{ref['source_ref_id']}")

    seen_gap_ids = set()

    seen_disputed_ids = set()

    seen_agent_suggested_ids = set()

    seen_flagged_ids = set()

    for note in review_notes:

        note_type = note.get("note_type")

        note_id = note.get("review_note_id")

        if note_type not in NOTE_TYPES:

            errors.append(f"{note_id}: geçersiz note_type: {note_type}")

            continue

        if note_type == "gap_note":

            seen_gap_ids.add(note_id)

            issue_id = note.get("source_issue_id")

            coverage = coverage_by_issue.get(issue_id)

            if coverage is None or coverage.get("block_reason") is None:

                errors.append(f"{note_id}: gap_note ilişkili coverage'ta block_reason=null.")

                continue

            if coverage.get("execution_state") == "analysis_not_run":

                errors.append(
                    f"{note_id}: gap_note execution_state='analysis_not_run' iken ÜRETİLEMEZ "
                    "(madde 6/B - eksiklik yalnız coverage/selection_scope/block_reason üzerinde "
                    "görünür kalmalıdır)."
                )

                continue

            expected_text = render_gap_note(coverage["block_reason"])

            if note.get("note_text") != expected_text:

                errors.append(f"{note_id}: note_text deterministik template ile eşleşmiyor.")

        elif note_type == "disputed_content":

            seen_disputed_ids.add(note_id)

            # state bilgisini şablon karşılaştırması için menu'den bul
            issue_id = note.get("source_issue_id")

            menu = allowlist_by_issue.get(issue_id, {})

            match = next(
                (e for e in menu.get("denied_timeline_events", []) if e["source_id"] == note.get("source_id")),
                None,
            )

            if match is None:

                errors.append(f"{note_id}: disputed_content ilişkili denied_timeline_event bulunamadı.")

                continue

            expected_text = render_disputed_content_note(match["source_id"], match["state"])

            if note.get("note_text") != expected_text:

                errors.append(f"{note_id}: note_text deterministik template ile eşleşmiyor.")

        elif note_type == "agent_suggested_citation_only":

            seen_agent_suggested_ids.add(note_id)

            expected_text = render_agent_suggested_citation_note(note.get("source_id"))

            if note.get("note_text") != expected_text:

                errors.append(f"{note_id}: note_text deterministik template ile eşleşmiyor.")

        elif note_type == "needs_review_flagged":

            seen_flagged_ids.add(note_id)

            section_id = None

            for s in sections:

                for r in refs_by_section.get(s["section_id"], []):

                    if r["source_field"] == note.get("source_field") and r["source_id"] == note.get("source_id"):

                        section_id = s["section_id"]

            if section_id is None:

                errors.append(f"{note_id}: needs_review_flagged ilişkili draft_source_ref bulunamadı.")

                continue

            expected_text = render_needs_review_flagged_note(section_id, note.get("source_field"), note.get("source_id"))

            if note.get("note_text") != expected_text:

                errors.append(f"{note_id}: note_text deterministik template ile eşleşmiyor.")

    if seen_gap_ids != expected_gap_ids:

        errors.append(f"gap_note kümesi eksik/fazla: beklenen={expected_gap_ids}, kayıtlı={seen_gap_ids}")

    if seen_disputed_ids != expected_disputed_ids:

        errors.append(
            f"disputed_content kümesi eksik/fazla: beklenen={expected_disputed_ids}, kayıtlı={seen_disputed_ids}"
        )

    if seen_agent_suggested_ids != expected_agent_suggested_ids:

        errors.append(
            "agent_suggested_citation_only kümesi eksik/fazla: "
            f"beklenen={expected_agent_suggested_ids}, kayıtlı={seen_agent_suggested_ids}"
        )

    if seen_flagged_ids != expected_flagged_ids:

        errors.append(
            f"needs_review_flagged kümesi eksik/fazla: beklenen={expected_flagged_ids}, kayıtlı={seen_flagged_ids}"
        )

    return errors


# ============================================================
# DRAFT AGENT SUGGESTIONS
# ============================================================

def validate_draft_agent_suggestions(suggestions, issue_index, known_reference_ids, fact_index=None):
    """
    Suggestion'lar section'larla AYNI bağımsız text-safety battery'sinden
    geçer (remediation madde 2/E) - forbidden-phrase YETERLİ DEĞİLDİR;
    ID-smuggling, doğrulanamayan alıntı ve desteklenmeyen tarih/tutar/
    süre/yıl AYRICA kontrol edilir. Agent'ın kendi doğrulama sonucuna
    GÜVENİLMEZ - bu fonksiyon TAMAMEN bağımsız yeniden hesaplar.
    """

    fact_index = fact_index or {}

    errors = []

    for suggestion in suggestions:

        suggestion_id = suggestion.get("suggestion_id")

        issue_id = suggestion.get("source_issue_id")

        if issue_id is not None and issue_id not in issue_index:

            errors.append(f"{suggestion_id}: bilinmeyen source_issue_id: {issue_id}")

        related_reference_ids = suggestion.get("related_reference_ids", [])

        for ref_id in related_reference_ids:

            if ref_id not in known_reference_ids:

                errors.append(f"{suggestion_id}: bilinmeyen related_reference_id: {ref_id}")

        text = suggestion.get("grounded_explanation")

        fact_ids_in_refs = [r for r in related_reference_ids if r in fact_index]

        citable_texts = collect_citable_texts(fact_index, fact_ids_in_refs)

        id_issues = find_id_reference_issues(text, related_reference_ids, known_reference_ids)

        if id_issues["fabricated"]:

            errors.append(
                f"{suggestion_id}: canonical'da hiç var olmayan, uydurma ID içeriyor: {id_issues['fabricated']}"
            )

        if id_issues["smuggled"]:

            errors.append(
                f"{suggestion_id}: gerçek ama başka issue'ya ait veya beyan edilmemiş ID içeriyor: {id_issues['smuggled']}"
            )

        unverified_quotes = find_unverified_quotes(text, citable_texts)

        if unverified_quotes:

            errors.append(f"{suggestion_id}: doğrulanamayan alıntı içeriyor: {unverified_quotes}")

        unsupported = find_unsupported_numeric_tokens(text, citable_texts)

        if unsupported:

            errors.append(f"{suggestion_id}: desteklenmeyen tarih/tutar/süre/yıl içeriyor: {unsupported}")

        forbidden_errors = check_forbidden_phrases_context(suggestion_id, text, "argument_summary", False)

        errors.extend(forbidden_errors)

    return errors


# ============================================================
# MAIN ENTRY
# ============================================================

def validate_drafting_analysis(drafting_path, expected_case_id=None, raise_on_error=False):

    drafting_path = Path(drafting_path)

    analysis = load_json(drafting_path)

    errors = []

    errors.extend(validate_schema(analysis))

    case_id = expected_case_id or analysis.get("case_id")

    errors.extend(validate_case_id(analysis, case_id))

    errors.extend(validate_generated_at(analysis))

    issue_context = load_canonical_issues(case_id)

    issue_index = issue_context["issue_index"]

    fact_context = load_canonical_fact_index(case_id)

    fact_index = fact_context["facts"]

    active_documents_index = build_active_documents_index(case_id)

    _e, evidence_candidate_index, evidence_path = load_canonical_evidence_optional(case_id)

    _r, research_index, research_path = load_canonical_legal_research_optional(case_id)

    _d, case_law_decision_index, case_law_path = load_canonical_case_law_optional(case_id)

    timeline_event_index, timeline_path = load_canonical_timeline_optional(case_id)

    deadlines, deadline_ids, deadline_path = load_canonical_deadline_optional(case_id)

    deadline_index = {d["deadline_id"]: d for d in deadlines}

    (
        claims, claim_index, counters, counter_index, rebuttals, rebuttal_index,
        argument_coverage_by_issue, arguments_path,
    ) = load_canonical_arguments_optional(case_id)

    risk_index, strategy_index, _rsa, risk_strategy_path = load_canonical_risk_strategy_optional(case_id)

    evidence_exists = evidence_path.exists()

    risk_strategy_exists = risk_strategy_path.exists()

    allowlist_by_issue, _w = build_allowlists_for_issues(
        issue_context["issues"], fact_index, active_documents_index, evidence_candidate_index,
        evidence_exists, research_index, case_law_decision_index, timeline_event_index, deadline_index,
        claim_index, counter_index, rebuttal_index, risk_index, strategy_index, risk_strategy_exists,
    )

    documents_hash_source = sorted(active_documents_index.items(), key=lambda kv: kv[0])

    analysis_metadata = analysis.get("analysis_metadata", {})

    current_hashes = {
        "issues_input_hash": (analysis_metadata.get("issues_input_hash"), sha256_of(issue_context["issues"]), True),
        "facts_input_hash": (
            analysis_metadata.get("facts_input_hash"),
            sha256_of({fid: rec["fact"] for fid, rec in fact_index.items()}), True,
        ),
        "documents_input_hash": (
            analysis_metadata.get("documents_input_hash"),
            sha256_of(documents_hash_source) if active_documents_index else None,
            bool(active_documents_index),
        ),
        "timeline_input_hash": (
            analysis_metadata.get("timeline_input_hash"),
            sha256_of(timeline_event_index) if timeline_path.exists() else None, timeline_path.exists(),
        ),
        "deadline_input_hash": (
            analysis_metadata.get("deadline_input_hash"),
            sha256_of(deadlines) if deadline_path.exists() else None, deadline_path.exists(),
        ),
        "legal_research_input_hash": (
            analysis_metadata.get("legal_research_input_hash"),
            sha256_of(research_index) if research_path.exists() else None, research_path.exists(),
        ),
        "case_law_input_hash": (
            analysis_metadata.get("case_law_input_hash"),
            sha256_of(case_law_decision_index) if case_law_path.exists() else None, case_law_path.exists(),
        ),
        "evidence_input_hash": (
            analysis_metadata.get("evidence_input_hash"),
            sha256_of(evidence_candidate_index) if evidence_exists else None, evidence_exists,
        ),
        "arguments_input_hash": (
            analysis_metadata.get("arguments_input_hash"),
            sha256_of({"claims": claim_index, "counters": counter_index, "rebuttals": rebuttal_index})
            if arguments_path.exists() else None,
            arguments_path.exists(),
        ),
        "risk_strategy_input_hash": (
            analysis_metadata.get("risk_strategy_input_hash"),
            sha256_of({"risks": risk_index, "strategies": strategy_index}) if risk_strategy_exists else None,
            risk_strategy_exists,
        ),
    }

    errors.extend(validate_analysis_metadata(analysis_metadata, current_hashes))

    selected_issue_ids = analysis_metadata.get("lawyer_input", {}).get("selected_issue_ids")

    sections = analysis.get("draft_sections", [])

    refs = analysis.get("draft_source_refs", [])

    errors.extend(
        validate_draft_coverage(
            analysis.get("draft_coverage", []), issue_index, allowlist_by_issue, selected_issue_ids, sections,
        )
    )

    errors.extend(validate_draft_source_refs(refs, sections, allowlist_by_issue))

    all_known_ids = (
        set(fact_index.keys()) | set(evidence_candidate_index.keys()) | set(research_index.keys())
        | set(case_law_decision_index.keys()) | set(timeline_event_index.keys()) | set(deadline_ids)
        | set(claim_index.keys()) | set(counter_index.keys()) | set(rebuttal_index.keys())
        | set(risk_index.keys()) | set(strategy_index.keys())
    )

    lawyer_provided_text = analysis_metadata.get("lawyer_input", {}).get("lawyer_provided_text")

    request_input = analysis_metadata.get("lawyer_input", {}).get("request_input")

    direct_lookup = {}

    for issue_id, menu in allowlist_by_issue.items():

        direct_lookup[("source_fact_ids", issue_id)] = set(menu["direct_fact_ids"])
        direct_lookup[("source_timeline_event_ids", issue_id)] = set(menu["direct_timeline_event_ids"])
        direct_lookup[("source_deadline_ids", issue_id)] = set(menu["direct_deadline_ids"])
        direct_lookup[("source_evidence_candidate_ids", issue_id)] = set(menu["direct_evidence_candidate_ids"])
        direct_lookup[("source_claim_ids", issue_id)] = set(menu["direct_claim_ids"])
        direct_lookup[("source_counterargument_ids", issue_id)] = set(menu["direct_counterargument_ids"])
        direct_lookup[("source_rebuttal_ids", issue_id)] = set(menu["direct_rebuttal_ids"])

    errors.extend(
        validate_draft_sections(
            sections, refs, allowlist_by_issue, fact_index, all_known_ids, lawyer_provided_text,
            request_input=request_input, direct_lookup=direct_lookup,
        )
    )

    errors.extend(
        validate_draft_review_notes(
            analysis.get("draft_review_notes", []), analysis.get("draft_coverage", []),
            allowlist_by_issue, sections, refs, direct_lookup,
        )
    )

    known_reference_ids = all_known_ids | {s["section_id"] for s in sections}

    errors.extend(
        validate_draft_agent_suggestions(
            analysis.get("draft_agent_suggestions", []), issue_index, known_reference_ids, fact_index,
        )
    )

    result = {"valid": len(errors) == 0, "errors": errors, "case_id": case_id}

    if raise_on_error and errors:

        raise ValueError("Drafting Validator FAIL:\n- " + "\n- ".join(errors))

    return result


# ============================================================
# SELF TEST
# ============================================================

def run_self_test(case_id="case_0001"):

    import tempfile

    from drafting_engine import (
        build_drafting_engine_output,
        atomic_write_json,
        snapshot_real_drafting_tree,
        assert_real_drafting_tree_unchanged,
    )

    print()
    print("======================================")
    print(" VERGİ AI - DRAFTING VALIDATOR V1")
    print("======================================")

    # snapshot_real_drafting_tree GERÇEK CASES_DIR/<case_id>/drafting yolunu
    # doğrudan hesaplar - bu self-test HİÇBİR path-döndüren fonksiyonu
    # monkeypatch ETMEZ, bu yüzden bu snapshot yanlışlıkla tempdir'e
    # yönlenme RİSKİ TAŞIMAZ (madde 7).
    real_tree_before = snapshot_real_drafting_tree(case_id)

    # NOT: Bu self-test gerçek case_0001/drafting/ dizinine HİÇ YAZMAZ -
    # yalnız izole bir tempdir'deki geçici bir dosya yolu kullanılır
    # (madde 7 - "Tüm mutation testleri izole TemporaryDirectory içinde
    # olmalı"). Gerçek pending yolu (get_pending_path) BU testte HİÇ
    # kullanılmaz - yalnız yetkilendirilmiş nihai çıktı için ayrılmıştır.

    temp_dir = tempfile.TemporaryDirectory(prefix="drafting_validator_selftest_")

    pending_path = Path(temp_dir.name) / f"drafting_{case_id}_v1.json.pending"

    try:

        offline = build_drafting_engine_output(case_id, lawyer_input=None, use_agent=False)

        atomic_write_json(pending_path, offline["analysis"])

        result = validate_drafting_analysis(pending_path, expected_case_id=case_id, raise_on_error=False)

        assert result["valid"] is True, result["errors"]

        print("T01 Offline baseline pending passes independent validator:", "PASS")

        # ---- T01b: CANONICAL'ın MEVCUT olduğu durum - aynı içerik,
        # canonical dosya adıyla (drafting.json) izole tempdir'de ----

        canonical_style_path = Path(temp_dir.name) / "drafting.json"

        atomic_write_json(canonical_style_path, offline["analysis"])

        result_canonical_exists = validate_drafting_analysis(
            canonical_style_path, expected_case_id=case_id, raise_on_error=False,
        )

        assert result_canonical_exists["valid"] is True, result_canonical_exists["errors"]

        print("T01c Canonical-named file (drafting.json, isolated tempdir) also validates correctly:", "PASS")

        # ---- T02: STALE INPUT HASH ----

        tampered = json.loads(json.dumps(offline["analysis"]))

        tampered["analysis_metadata"]["facts_input_hash"] = "0" * 64

        atomic_write_json(pending_path, tampered)

        result2 = validate_drafting_analysis(pending_path, expected_case_id=case_id, raise_on_error=False)

        assert result2["valid"] is False
        assert any("STALE" in e for e in result2["errors"])

        print("T02 Stale facts_input_hash detected:", "PASS")

        # ---- T03: TAMPERED lawyer_input_hash (should not match recompute) ----

        tampered2 = json.loads(json.dumps(offline["analysis"]))

        tampered2["analysis_metadata"]["lawyer_input"]["draft_intent_type"] = "statement_on_merits"

        atomic_write_json(pending_path, tampered2)

        result3 = validate_drafting_analysis(pending_path, expected_case_id=case_id, raise_on_error=False)

        assert result3["valid"] is False
        assert any("lawyer_input_hash" in e for e in result3["errors"])

        print("T03 Tampered lawyer_input (without matching hash update) detected:", "PASS")

        # ---- T04: selection_scope tamper ----

        partial = build_drafting_engine_output(
            case_id, lawyer_input={"selected_issue_ids": ["issue_001"]}, use_agent=False,
        )

        atomic_write_json(pending_path, partial["analysis"])

        result4 = validate_drafting_analysis(pending_path, expected_case_id=case_id, raise_on_error=False)

        assert result4["valid"] is True, result4["errors"]

        tampered4 = json.loads(json.dumps(partial["analysis"]))

        for c in tampered4["draft_coverage"]:

            if c["source_issue_id"] == "issue_002":

                c["selection_scope"] = "selected"

        atomic_write_json(pending_path, tampered4)

        result5 = validate_drafting_analysis(pending_path, expected_case_id=case_id, raise_on_error=False)

        assert result5["valid"] is False
        assert any("selection_scope" in e for e in result5["errors"])

        print("T04 Tampered selection_scope (independent recompute) rejected:", "PASS")

    finally:

        temp_dir.cleanup()

    assert_real_drafting_tree_unchanged(case_id, real_tree_before, "End of drafting_validator self-test")

    print("T05 Real case_0001/drafting/ tree unchanged throughout (regression-catching invariant):", "PASS")

    print()
    print("======================================")
    print(" DRAFTING VALIDATOR V1: 6/6 PASS")
    print("======================================")


def main():

    parser = argparse.ArgumentParser(description="Vergi AI Drafting Validator V1")

    parser.add_argument("--case", dest="case_id", default=DEFAULT_CASE_ID)

    parser.add_argument("--drafting", dest="drafting_path", default=None)

    parser.add_argument("--self-test", action="store_true", dest="self_test")

    args = parser.parse_args()

    if args.self_test or args.drafting_path is None:

        run_self_test(args.case_id)

        return

    print()
    print("======================================")
    print(" VERGİ AI - DRAFTING VALIDATOR V1")
    print("======================================")

    result = validate_drafting_analysis(
        drafting_path=Path(args.drafting_path), expected_case_id=args.case_id, raise_on_error=False,
    )

    print()
    print("Case:", result["case_id"])

    for error in result["errors"]:

        print("-", error)

    print()
    print("======================================")
    print(" DRAFTING VALIDATOR V1:", "PASS" if result["valid"] else "FAIL")
    print("======================================")

    if not result["valid"]:

        import sys

        sys.exit(1)


if __name__ == "__main__":

    main()
