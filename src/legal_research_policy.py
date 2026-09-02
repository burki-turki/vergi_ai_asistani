# ============================================================
# VERGİ AI - LEGAL RESEARCH POLICY V1
#
# AMAÇ
# ----
#
# Canonical issue candidate'lar (issues.json) içindeki hukuki
# dayanak atıflarını (citation), MEVCUT deterministik Legal
# Knowledge Engine (provision_repository + provision_version_policy
# + provision_policy) üzerinden çözümleyip, hukuki ARAŞTIRMA
# candidate'ları üretmek.
#
#
# TEMEL PRENSİP
# -------------
#
# Bu modül Legal Knowledge Engine'i YENİDEN İMPLEMENT ETMEZ.
# provision_repository.resolve_provisions() / provision_version_policy
# .select_provision_versions() / provision_policy.evaluate_provision_policy()
# TEK gerçek karar noktalarıdır; bu modül yalnız:
#
#   1. Bir citation string'ini (ör. "KDVK_m29", "IYUK_2577_m8_3")
#      bu fonksiyonların beklediği (document_id, madde, fikra, bent)
#      parametrelerine ayrıştırır (parse_citation_ref - salt
#      string ayrıştırma, hukuki karar DEĞİLDİR),
#
#   2. Bu deterministik fonksiyonları çağırır,
#
#   3. Sonucu, insan onayı gerektiren bir "research candidate"
#      olarak paketler.
#
#
# RESEARCH CANDIDATE NE DEĞİLDİR
# --------------------------------
#
#   != hükmün yürürlükte olduğunun kesinleşmesi
#   != applicability'nin kesinleşmesi
#   != case outcome
#   != kesin hukuki sonuç
#
# formal_result / applicability_result alanları, provision_policy.py
# TARAFINDAN ÜRETİLMİŞ deterministik, fail-closed bulgulardır
# (ör. doğrulanmamışsa "unknown" döner - bkz. provision_policy.py).
# Bu alanların varlığı, bulgunun insan onayı olmadan nihai kabul
# edildiği anlamına GELMEZ (bkz. her candidate'taki notes alanı).
#
#
# KURALLAR (V1)
# -------------
#
# R1 - research_rule_fact_legal_reference_v1
#      Bir issue'nun source_fact_ids'i arasında fact_kind=
#      "legal_reference" olan bir fact varsa, o fact'in
#      structured_values içindeki reference_value citation'ı
#      çözümlenir.
#
# R2 - research_rule_deadline_legal_basis_v1
#      Bir issue'nun source_deadline_ids'i arasında bir canonical
#      deadline varsa, o deadline'ın legal_basis_refs listesindeki
#      TÜM citation'lar TEK bir research candidate'ta toplanarak
#      çözümlenir (aynı deadline rule'unun dayanağı oldukları için).
# ============================================================


import json
import re

from pathlib import Path


from provision_repository import (
    get_enabled_provisions,
    resolve_provisions,
)

from provision_version_policy import (
    select_provision_versions,
)

from provision_policy import (
    evaluate_provision_policy,
)


# ============================================================
# VERSION
# ============================================================

LEGAL_RESEARCH_POLICY_VERSION = "1"


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

LEGAL_DOCUMENTS_PATH = (
    DATA_DIR
    / "documents.json"
)


# ============================================================
# RULE IDS
# ============================================================

RULE_FACT_LEGAL_REFERENCE = (
    "research_rule_fact_legal_reference_v1"
)

RULE_DEADLINE_LEGAL_BASIS = (
    "research_rule_deadline_legal_basis_v1"
)


# ============================================================
# CITATION PREFIX -> DOCUMENT ID (THIN PARSING TABLE)
#
# Bu, hukuki bir karar DEĞİLDİR; yalnız bir citation string'ini
# provision_repository.resolve_provisions()'ın beklediği
# document_id parametresine çeviren bir kısaltma tablosudur.
# Eşleşen bir document_id, provisions.json/documents.json içinde
# BULUNMAYABİLİR - bu durumda repository doğal olarak
# "not_found" döner (fail-closed).
# ============================================================

CITATION_PREFIX_TO_DOCUMENT_ID = {
    "IYUK":
        "kanun_2577",

    "VUK":
        "kanun_213",

    "KDVK":
        "kanun_3065",
}


# ============================================================
# CITATION PATTERNS
#
# Desteklenen örnekler:
#
#   KDVK_m29                -> prefix=KDVK, madde=29
#   VUK_m341                -> prefix=VUK, madde=341
#   IYUK_2577_m7_1          -> prefix=IYUK, number=2577, madde=7, fikra=1
#   IYUK_2577_m7_2_b        -> prefix=IYUK, number=2577, madde=7, fikra=2, bent=b
# ============================================================

CITATION_PATTERN_LONG = re.compile(
    r"^(?P<prefix>[A-Za-zÇĞİÖŞÜçğıöşü]+)"
    r"_(?P<number>\d+)"
    r"_m(?P<madde>\d+[A-Za-z]?)"
    r"(?:_(?P<fikra>\d+))?"
    r"(?:_(?P<bent>[A-Za-zÇĞİÖŞÜçğıöşü]+))?$"
)

CITATION_PATTERN_SHORT = re.compile(
    r"^(?P<prefix>[A-Za-zÇĞİÖŞÜçğıöşü]+)"
    r"_m(?P<madde>\d+[A-Za-z]?)"
    r"(?:_(?P<fikra>\d+))?"
    r"(?:_(?P<bent>[A-Za-zÇĞİÖŞÜçğıöşü]+))?$"
)


def parse_citation_ref(
    citation_ref,
):

    if (
        not isinstance(
            citation_ref,
            str,
        )
        or not citation_ref.strip()
    ):

        return {
            "valid":
                False,

            "citation_ref":
                citation_ref,

            "error":
                "citation_ref boş veya string değil.",
        }

    value = citation_ref.strip()

    match = (
        CITATION_PATTERN_LONG.fullmatch(
            value
        )
        or CITATION_PATTERN_SHORT.fullmatch(
            value
        )
    )

    if not match:

        return {
            "valid":
                False,

            "citation_ref":
                value,

            "error":
                "Desteklenmeyen citation formatı.",
        }

    groups = match.groupdict()

    prefix = groups[
        "prefix"
    ].upper()

    document_id = (
        CITATION_PREFIX_TO_DOCUMENT_ID.get(
            prefix
        )
    )

    return {
        "valid":
            True,

        "citation_ref":
            value,

        "prefix":
            prefix,

        "document_id":
            document_id,

        "known_prefix":
            document_id is not None,

        "madde":
            groups.get(
                "madde"
            ),

        "fikra":
            groups.get(
                "fikra"
            ),

        "bent":
            groups.get(
                "bent"
            ),

        "error":
            None,
    }


# ============================================================
# LEGAL DOCUMENTS MANIFEST (documents.json) - YALNIZ OKUMA
# ============================================================

def load_legal_documents_index():

    if not LEGAL_DOCUMENTS_PATH.exists():

        return {}

    with open(
        LEGAL_DOCUMENTS_PATH,
        "r",
        encoding="utf-8",
    ) as file:

        manifest = json.load(
            file
        )

    index = {}

    for document in manifest.get(
        "documents",
        [],
    ):

        document_id = document.get(
            "document_id"
        )

        if document_id:

            index[
                document_id
            ] = document

    return index


def get_document_short_title(
    documents_index,
    document_id,
):

    document = documents_index.get(
        document_id
    )

    if not document:

        return document_id

    return (
        document.get(
            "short_title"
        )
        or document.get(
            "title"
        )
        or document_id
    )


# ============================================================
# ALLOWED PROVISION IDS (GROUNDING SET FOR AGENT LAYER)
# ============================================================

def get_all_provision_ids():

    provisions = (
        get_enabled_provisions()
    )

    ids = set()

    for provision in provisions:

        provision_id = provision.get(
            "provision_id"
        )

        if provision_id:

            ids.add(
                provision_id
            )

    return ids


# ============================================================
# RESOLVE ONE CITATION
#
# TEK gerçek karar noktası burada değil, çağrılan
# provision_repository / provision_version_policy /
# provision_policy fonksiyonlarındadır.
# ============================================================

# ============================================================
# FINDING STATUS SEMANTICS
#
# ÖNEMLİ: "provision_resolved" SÖZCÜĞÜ YALNIZ ŞU ANLAMA GELİR:
#
#   "Bu madde/fıkra/bent canonical provisions.json repository'sinde
#    bulunmuştur VE version/temporal sorgusu tek bir sürüme
#    ulaşmıştır."
#
# "provision_resolved" ASLA şu anlama GELMEZ:
#
#   - hukuki meselenin çözüldüğü
#   - hükmün nihai olarak uygulanabilir olduğu
#   - davanın sonucu
#
# formal_result / applicability_result alanları AYRI, KENDİ
# başlarına değerlendirilmesi gereken deterministik bulgulardır
# (ör. applicability_result="unknown" iken hiçbir kayıt
# "uygulanabilir olduğu çözüldü" anlamına GELMEZ - bkz.
# case_legal_research.schema.json içindeki finding_status
# "description" alanı ve Legal Research Validator V1
# validate_finding_consistency()).
# ============================================================

FINDING_STATUS_NOT_RESOLVED = {
    "version_conflict",
    "version_unresolved",
    "no_valid_version",
    "mixed_provision_candidates",
    "ambiguous",
    "not_found",
    "unparseable_citation",
    "no_research_evidence",
    "retrieval_not_run",
    "retrieval_failed",
}

# ============================================================
# EXECUTION-STATE FINDING STATUSES (ISSUE-DRIVEN DISCOVERY)
#
# ÜÇ AYRI ANLAM - BİRBİRİNE DÖNÜŞTÜRÜLEMEZ:
#
#   retrieval_not_run   : research intent oluştu, retrieval
#                          HENÜZ DENENMEDİ (ör. network kapalı).
#                          "search yapılmadı" ASLA "kaynak yok"
#                          anlamına gelmez.
#
#   retrieval_failed     : retrieval DENENDİ ama teknik olarak
#                          başarısız oldu (exception, import
#                          hatası, geçersiz sonuç formatı).
#                          "retriever çöktü" ASLA "kaynak yok"
#                          anlamına gelmez.
#
#   no_research_evidence : retrieval BAŞARIYLA çalıştı ve
#                          mekanik olarak hiçbir aday
#                          döndürmedi/failure_reason verdi.
#                          Bu, gerçekten "arandı ve bulunamadı"
#                          anlamına gelir.
# ============================================================

EXECUTION_STATE_FINDING_STATUSES = {
    "retrieval_not_run",
    "retrieval_failed",
    "no_research_evidence",
}

FINDING_STATUS_RESOLVED = {
    "provision_resolved",
    "provision_resolved_version_unknown",
}


# ============================================================
# RESOLVE PROVISION LOCATOR
#
# TEK gerçek karar noktası burada değil, çağrılan
# provision_repository / provision_version_policy /
# provision_policy fonksiyonlarındadır. Bu fonksiyon HEM
# explicit citation path'i (resolve_citation) HEM DE
# issue-driven discovery path'i (legal_research_discovery.py)
# tarafından ORTAK olarak kullanılır - iki yerde
# tekrarlanmaz.
# ============================================================

def resolve_provision_locator(
    document_id,
    madde,
    fikra=None,
    bent=None,
    temporal_mode="neutral",
    query_date=None,
):

    if not document_id:

        return {
            "finding_status":
                "not_found",

            "resolved_provision_ids": [],

            "selected_provision":
                None,

            "formal":
                None,

            "applicability":
                None,
        }

    repository_result = (
        resolve_provisions(
            document_id=
                document_id,

            madde=
                madde,

            fikra=
                fikra,

            bent=
                bent,
        )
    )

    repository_status = (
        repository_result.get(
            "status"
        )
    )

    if repository_status == "not_found":

        return {
            "finding_status":
                "not_found",

            "resolved_provision_ids": [],

            "selected_provision":
                None,

            "formal":
                None,

            "applicability":
                None,
        }

    if repository_status == "ambiguous":

        return {
            "finding_status":
                "ambiguous",

            "resolved_provision_ids": [],

            "selected_provision":
                None,

            "formal":
                None,

            "applicability":
                None,
        }

    # ========================================================
    # REPOSITORY STATUS == "resolved"
    #
    # (repository_result["status"]=="resolved" yalnız
    # provision_repository.py'nin locator eşleşmesini bulduğu
    # anlamına gelir; version/formal/applicability henüz
    # belirlenmemiştir - onlar aşağıda ayrıca çözülür.)
    # ========================================================

    candidates = repository_result.get(
        "candidates",
        [],
    )

    version_result = (
        select_provision_versions(
            candidates=
                candidates,

            temporal_mode=
                temporal_mode,

            query_date=
                query_date,
        )
    )

    selection_status = (
        version_result.get(
            "selection_status"
        )
    )

    if selection_status in {
        "selected",
        "unknown",
        "neutral",
    }:

        selected_candidates = (
            version_result.get(
                "selected_candidates",
                [],
            )
        )

        if not selected_candidates:

            return {
                "finding_status":
                    "version_unresolved",

                "resolved_provision_ids": [],

                "selected_provision":
                    None,

                "formal":
                    None,

                "applicability":
                    None,
            }

        selected_provision = selected_candidates[
            0
        ]

        policy_result = (
            evaluate_provision_policy(
                provision=
                    selected_provision,

                temporal_mode=
                    temporal_mode,

                query_date=
                    query_date,

                question_scope=
                    "both",
            )
        )

        finding_status = (
            "provision_resolved"
            if selection_status
            == "selected"
            else "provision_resolved_version_unknown"
        )

        return {
            "finding_status":
                finding_status,

            "resolved_provision_ids": [
                provision.get(
                    "provision_id"
                )
                for provision
                in selected_candidates
                if provision.get(
                    "provision_id"
                )
            ],

            "selected_provision":
                selected_provision,

            "formal":
                policy_result[
                    "formal"
                ],

            "applicability":
                policy_result[
                    "applicability"
                ],
        }

    # ========================================================
    # version_conflict / version_unresolved / no_valid_version /
    # mixed_provision_candidates / no_candidates
    # ========================================================

    finding_status_map = {
        "version_conflict":
            "version_conflict",

        "version_unresolved":
            "version_unresolved",

        "no_valid_version":
            "no_valid_version",

        "mixed_provision_candidates":
            "mixed_provision_candidates",

        "no_candidates":
            "not_found",
    }

    return {
        "finding_status":
            finding_status_map.get(
                selection_status,
                "version_unresolved",
            ),

        "resolved_provision_ids": [],

        "selected_provision":
            None,

        "formal":
            None,

        "applicability":
            None,
    }


# ============================================================
# RESOLVE ONE CITATION (EXPLICIT CITATION PATH)
# ============================================================

def resolve_citation(
    citation_ref,
    temporal_mode="neutral",
    query_date=None,
):

    parsed = (
        parse_citation_ref(
            citation_ref
        )
    )

    if not parsed[
        "valid"
    ]:

        return {
            "citation_ref":
                citation_ref,

            "parsed":
                parsed,

            "finding_status":
                "unparseable_citation",

            "resolved_provision_ids": [],

            "selected_provision":
                None,

            "formal":
                None,

            "applicability":
                None,
        }

    if not parsed[
        "known_prefix"
    ]:

        # ----------------------------------------------------
        # Bilinmeyen prefix; yine de repository'de arama
        # denenmez çünkü document_id yok. Fail-closed:
        # not_found ile aynı anlam - kaynak Legal Knowledge
        # Engine'de bulunamadı.
        # ----------------------------------------------------

        return {
            "citation_ref":
                citation_ref,

            "parsed":
                parsed,

            "finding_status":
                "not_found",

            "resolved_provision_ids": [],

            "selected_provision":
                None,

            "formal":
                None,

            "applicability":
                None,
        }

    locator_result = (
        resolve_provision_locator(
            document_id=
                parsed[
                    "document_id"
                ],

            madde=
                parsed[
                    "madde"
                ],

            fikra=
                parsed[
                    "fikra"
                ],

            bent=
                parsed[
                    "bent"
                ],

            temporal_mode=
                temporal_mode,

            query_date=
                query_date,
        )
    )

    return {
        "citation_ref":
            citation_ref,

        "parsed":
            parsed,

        **locator_result,
    }


# ============================================================
# CONFIDENCE BY FINDING STATUS
# ============================================================

CONFIDENCE_BY_FINDING_STATUS = {
    "provision_resolved":
        0.9,

    "provision_resolved_version_unknown":
        0.6,

    "version_conflict":
        0.4,

    "version_unresolved":
        0.4,

    "no_valid_version":
        0.4,

    "mixed_provision_candidates":
        0.4,

    "ambiguous":
        0.4,

    "not_found":
        0.3,

    "unparseable_citation":
        0.2,

    "no_research_evidence":
        0.2,

    "retrieval_failed":
        0.1,

    "retrieval_not_run":
        0.1,
}


# ============================================================
# RENDER - DETERMINISTIC TITLE / DESCRIPTION
#
# LLM İÇERMEZ. Yalnız sabit Türkçe şablonlar + resolve_citation()
# çıktısı + documents.json'dan alınan short_title kullanılır.
# ============================================================

def render_citation_findings(
    citation_results,
    documents_index,
):

    lines = []

    for result in citation_results:

        citation_ref = result[
            "citation_ref"
        ]

        finding_status = result[
            "finding_status"
        ]

        if finding_status in FINDING_STATUS_RESOLVED:

            provision = result[
                "selected_provision"
            ]

            document_id = (
                provision.get(
                    "document_id"
                )
            )

            short_title = (
                get_document_short_title(
                    documents_index,
                    document_id,
                )
            )

            formal = result[
                "formal"
            ]

            applicability = result[
                "applicability"
            ]

            lines.append(
                f"'{citation_ref}' → "
                f"{provision.get('provision_id')} "
                f"({short_title}). Deterministik Legal "
                f"Knowledge Engine bulgusu: "
                f"formal_result='{formal['result']}' "
                f"({formal['reason']}), "
                f"applicability_result="
                f"'{applicability['result']}' "
                f"({applicability['reason']})."
            )

        elif finding_status == "not_found":

            lines.append(
                f"'{citation_ref}' → Legal Knowledge "
                "Engine'de eşleşen bir kayıt bulunamadı "
                "(not_found)."
            )

        elif finding_status == "ambiguous":

            lines.append(
                f"'{citation_ref}' → birden fazla farklı "
                "provision arasında belirsizlik var "
                "(ambiguous)."
            )

        elif finding_status == "unparseable_citation":

            lines.append(
                f"'{citation_ref}' → citation formatı "
                "ayrıştırılamadı (unparseable_citation)."
            )

        else:

            lines.append(
                f"'{citation_ref}' → sürüm/uygulanabilirlik "
                f"belirsizliği nedeniyle çözümlenemedi "
                f"({finding_status})."
            )

    return " ".join(
        lines
    )


DISCLAIMER_NOTE = (
    "Bu kayıt, deterministik Legal Knowledge Engine "
    "(provision_repository + provision_version_policy + "
    "provision_policy) tarafından üretilmiş bir araştırma "
    "adayıdır. Hükmün yürürlükte olduğunu, uygulanabilir "
    "olduğunu, davanın sonucunu veya kesin bir hukuki "
    "sonucu KESİNLEŞTİRMEZ; insan onayı gerektirir."
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


def get_fact_reference_values(
    fact,
):

    values = []

    for structured_value in fact.get(
        "structured_values",
        [],
    ):

        if (
            isinstance(
                structured_value,
                dict,
            )
            and structured_value.get(
                "value_type"
            )
            == "reference"
        ):

            reference_value = (
                structured_value.get(
                    "reference_value"
                )
            )

            if reference_value:

                values.append(
                    reference_value
                )

    return values


# ============================================================
# R1 - FACT LEGAL REFERENCE
# ============================================================

def apply_rule_fact_legal_reference(
    issue,
    fact_index,
    documents_index,
):

    candidates = []

    for fact_id in issue.get(
        "source_fact_ids",
        [],
    ):

        record = fact_index.get(
            fact_id
        )

        if not record:

            continue

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

        citation_refs = (
            get_fact_reference_values(
                fact
            )
        )

        if not citation_refs:

            continue

        citation_results = [
            resolve_citation(
                citation_ref,
                temporal_mode=
                    "neutral",
            )
            for citation_ref
            in citation_refs
        ]

        resolved_provision_ids = (
            unique_strings(
                [
                    provision_id
                    for result
                    in citation_results
                    for provision_id
                    in result[
                        "resolved_provision_ids"
                    ]
                ]
            )
        )

        overall_finding_status = (
            citation_results[
                0
            ][
                "finding_status"
            ]
        )

        confidence = (
            CONFIDENCE_BY_FINDING_STATUS.get(
                overall_finding_status,
                0.3,
            )
        )

        first_result = citation_results[
            0
        ]

        formal = (
            first_result[
                "formal"
            ][
                "result"
            ]
            if first_result[
                "formal"
            ]
            else None
        )

        applicability = (
            first_result[
                "applicability"
            ][
                "result"
            ]
            if first_result[
                "applicability"
            ]
            else None
        )

        candidates.append(
            {
                "research_type":
                    "provision_resolution",

                "source_issue_id":
                    issue[
                        "issue_id"
                    ],

                "title":
                    (
                        "Fact'te atıf yapılan hukuki "
                        "dayanak Legal Knowledge Engine "
                        "üzerinden araştırıldı"
                    ),

                "description":
                    render_citation_findings(
                        citation_results,
                        documents_index,
                    )
                    + " "
                    + DISCLAIMER_NOTE,

                "trigger_rule_id":
                    RULE_FACT_LEGAL_REFERENCE,

                "citation_refs":
                    citation_refs,

                "resolved_provision_ids":
                    resolved_provision_ids,

                "finding_status":
                    overall_finding_status,

                "formal_result":
                    formal,

                "applicability_result":
                    applicability,

                "retrieval_query":
                    None,

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
                    confidence,

                "requires_human_review":
                    True,

                "notes":
                    None,
            }
        )

    return candidates


# ============================================================
# R2 - DEADLINE LEGAL BASIS
# ============================================================

def apply_rule_deadline_legal_basis(
    issue,
    deadline_index,
    documents_index,
):

    candidates = []

    for deadline_id in issue.get(
        "source_deadline_ids",
        [],
    ):

        deadline = deadline_index.get(
            deadline_id
        )

        if not deadline:

            continue

        citation_refs = (
            unique_strings(
                deadline.get(
                    "legal_basis_refs",
                    [],
                )
            )
        )

        if not citation_refs:

            continue

        anchor_date = deadline.get(
            "anchor_date"
        )

        temporal_mode = (
            "historical_date"
            if anchor_date
            else "neutral"
        )

        citation_results = [
            resolve_citation(
                citation_ref,
                temporal_mode=
                    temporal_mode,

                query_date=
                    anchor_date,
            )
            for citation_ref
            in citation_refs
        ]

        resolved_provision_ids = (
            unique_strings(
                [
                    provision_id
                    for result
                    in citation_results
                    for provision_id
                    in result[
                        "resolved_provision_ids"
                    ]
                ]
            )
        )

        # ----------------------------------------------------
        # Birden fazla citation aynı deadline rule'unu
        # destekler; en "sorunlu" (en düşük confidence)
        # bulguyu genel finding_status olarak yansıt -
        # fail-closed: tek bir çözülemeyen citation bile
        # bulunsa genel sonuç "resolved" gösterilmez.
        # ----------------------------------------------------

        worst_result = min(
            citation_results,
            key=lambda result:
                CONFIDENCE_BY_FINDING_STATUS.get(
                    result[
                        "finding_status"
                    ],
                    0.0,
                ),
        )

        overall_finding_status = worst_result[
            "finding_status"
        ]

        confidence = (
            CONFIDENCE_BY_FINDING_STATUS.get(
                overall_finding_status,
                0.3,
            )
        )

        formal = (
            worst_result[
                "formal"
            ][
                "result"
            ]
            if worst_result[
                "formal"
            ]
            else None
        )

        applicability = (
            worst_result[
                "applicability"
            ][
                "result"
            ]
            if worst_result[
                "applicability"
            ]
            else None
        )

        candidates.append(
            {
                "research_type":
                    "provision_resolution",

                "source_issue_id":
                    issue[
                        "issue_id"
                    ],

                "title":
                    (
                        "Deadline kaydının hukuki "
                        "dayanakları Legal Knowledge "
                        "Engine üzerinden araştırıldı"
                    ),

                "description":
                    render_citation_findings(
                        citation_results,
                        documents_index,
                    )
                    + " "
                    + DISCLAIMER_NOTE,

                "trigger_rule_id":
                    RULE_DEADLINE_LEGAL_BASIS,

                "citation_refs":
                    citation_refs,

                "resolved_provision_ids":
                    resolved_provision_ids,

                "finding_status":
                    overall_finding_status,

                "formal_result":
                    formal,

                "applicability_result":
                    applicability,

                "retrieval_query":
                    None,

                "source_fact_ids": [],

                "source_timeline_event_ids":
                    unique_strings(
                        [
                            deadline.get(
                                "anchor_event_id"
                            )
                        ]
                        if deadline.get(
                            "anchor_event_id"
                        )
                        else []
                    ),

                "source_deadline_ids": [
                    deadline_id
                ],

                "related_party_ids": [],

                "related_dispute_item_ids": [],

                "confidence":
                    confidence,

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
    issues,
    fact_index,
    deadline_index,
    documents_index,
):

    candidates = []

    for issue in issues:

        candidates.extend(
            apply_rule_fact_legal_reference(
                issue,
                fact_index,
                documents_index,
            )
        )

        candidates.extend(
            apply_rule_deadline_legal_basis(
                issue,
                deadline_index,
                documents_index,
            )
        )

    return candidates


# ============================================================
# FINALIZE CANDIDATES
#
# research_id atar ve status="candidate" sabitler. Hem Engine
# hem de Validator self-test tarafından kullanılır.
# ============================================================

def finalize_candidates(
    candidates,
    start_index=1,
):

    finalized = []

    for index, candidate in enumerate(
        candidates,
        start=start_index,
    ):

        research = dict(
            candidate
        )

        research[
            "research_id"
        ] = f"research_{index:03d}"

        research[
            "status"
        ] = "candidate"

        finalized.append(
            research
        )

    return finalized
