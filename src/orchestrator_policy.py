# ============================================================
# VERGİ AI - ORCHESTRATOR POLICY V1 (Row 17)
#
# Saf deterministik sabitler ve düşük seviyeli primitifler. Bu
# modül HİÇBİR dosya I/O'su, LLM/network çağrısı yapmaz;
# orchestrator_discovery/orchestrator_engine/orchestrator_validator'ın
# import ettiği ORTAK katmandır (Row 16 qa_policy.py ile aynı
# desen, Prensip 10: mevcut düşük seviye primitifler - sha256,
# canonical_dumps - yeniden yazılmaz, qa_policy'den import edilir).
# ============================================================

from qa_policy import canonical_dumps, sha256_of, sha256_of_bytes  # noqa: F401


# ============================================================
# ORCHESTRATOR'IN OKUDUĞU 11 SABİT KAYNAK (Row 17 contract -
# değiştirilemez). "documents"/"facts" burada YOKTUR - Row 17
# doküman/fact seviyesinde DEĞİL, issue seviyesinde birleştirir;
# facts zaten issues.json'un source_fact_ids'i üzerinden ve
# case.json üzerinden dolaylı olarak erişilebilir kalır.
# ============================================================

ORCHESTRATOR_SOURCE_REGISTRY = (
    "case",
    "timeline",
    "deadline",
    "issues",
    "legal_research",
    "case_law",
    "evidence",
    "arguments",
    "risk_strategy",
    "drafting",
    "qa",
)

# Yalnız 'evidence' opsiyoneldir (Row 12 checkpoint: canonical
# evidence.json henüz OLUŞTURULMAMIŞ olabilir - KASITLI bir
# durumdur, kontrat ihlali DEĞİLDİR. Row 16'nın QA_OPTIONAL_SCOPES
# ile AYNI ilke).
ORCHESTRATOR_OPTIONAL_SOURCES = frozenset({"evidence"})

CHECK_VERSION = "1"
CASE_VIEW_SCHEMA_VERSION = 1


# ============================================================
# ARTIFACT STATE SABİTLERİ (Row 16 ile birebir aynı taksonomi -
# yeni bir sözlük İCAT EDİLMEZ, aynı dört değer yeniden kullanılır)
# ============================================================

ARTIFACT_STATE_PRESENT_VALID = "present_valid"
ARTIFACT_STATE_PRESENT_INVALID = "present_invalid"
ARTIFACT_STATE_ABSENT = "absent"
ARTIFACT_STATE_UNREADABLE = "unreadable"


# ============================================================
# OPEN-ITEM KIND SABİTLERİ - Row 17'nin YENİ bir sınıflandırma
# İCAT ETMEDİĞİNİ, yalnız var olan alanları TEK LİSTEYE
# topladığını netleştirir.
# ============================================================

OPEN_ITEM_KIND_REQUIRES_HUMAN_REVIEW = "requires_human_review"
OPEN_ITEM_KIND_NEEDS_REVIEW_STATE = "needs_review_state"
OPEN_ITEM_KIND_QA_BLOCKED = "qa_blocked"
OPEN_ITEM_KIND_QA_FAILED = "qa_failed"

OPEN_ITEM_KINDS = (
    OPEN_ITEM_KIND_REQUIRES_HUMAN_REVIEW,
    OPEN_ITEM_KIND_NEEDS_REVIEW_STATE,
    OPEN_ITEM_KIND_QA_BLOCKED,
    OPEN_ITEM_KIND_QA_FAILED,
)


def group_by_issue_id(records, issue_field="source_issue_id"):
    """
    Saf yardımcı: bir kayıt listesini source_issue_id'ye göre
    gruplar. Bilinmeyen/eksik issue_field'lı kayıtlar SESSİZCE
    ATILMAZ - ayrı bir "unlinked" anahtarı altında toplanır ki
    hiçbir kayıt kaybolmasın (fail-closed, Prensip 9).
    """

    grouped = {}
    unlinked = []

    for record in records:

        if not isinstance(record, dict):

            continue

        issue_id = record.get(issue_field)

        if not issue_id:

            unlinked.append(record)
            continue

        grouped.setdefault(issue_id, []).append(record)

    return grouped, unlinked


def group_by_issue_id_membership(records, issue_field="source_issue_ids"):
    """
    group_by_issue_id'nin ÇOĞUL versiyonu (drafting.draft_sections
    gibi bir kaydın BİRDEN FAZLA issue'ya ait olabildiği durumlar
    için). Bir kayıt, source_issue_ids listesindeki HER issue_id
    altında ayrı ayrı görünür - bu bir KOPYALAMA HATASI DEĞİL,
    gerçek çoklu-üyeliktir (case_view.schema.json'da belgelenmiştir).
    """

    grouped = {}
    unlinked = []

    for record in records:

        if not isinstance(record, dict):

            continue

        issue_ids = record.get(issue_field) or []

        if not isinstance(issue_ids, list) or not issue_ids:

            unlinked.append(record)
            continue

        for issue_id in issue_ids:

            grouped.setdefault(issue_id, []).append(record)

    return grouped, unlinked


if __name__ == "__main__":

    print("orchestrator_policy.py - saf modül, self-test yok.")
