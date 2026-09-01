# ============================================================
# VERGİ AI - RAG QUALITY EVALUATION V5
#
# RAG V3.4
#
# TEST KAPSAMI
#
# T01-T06
#   Temel Legal RAG
#
# T07-T11
#   Document Temporal + Version
#
# T12-T13
#   Version fail-closed
#
# T14-T15
#   Legal safety
#
# T16-T19
#   Provision Repository + Applicability Policy
#
#
# KRİTİK AYRIM:
#
# document temporal
#       !=
# provision formal status
#       !=
# provision applicability
#
#
# V5 İLE KALICI OLARAK TEST EDİLEN DAVRANIŞ:
#
# 10.11.2016
#   applicability = applicable
#
# 2020
#   applicability = not_applicable
#
# AMA:
#
# 2020 provision formal status
#   = unknown
#
#
# Böylece:
#
# "başvuru süresi kapalı"
#
# ile
#
# "hüküm mülga"
#
# birbirine karıştırılmaz.
# ============================================================


import copy

import rag as rag_module


# ============================================================
# TEST CASES
# ============================================================

TEST_CASES = [

    # ========================================================
    # T01
    # ========================================================

    {
        "id": "T01",

        "name":
            "Doğrudan madde/fıkra sorusu",

        "runner":
            "normal",

        "question":
            (
                "6736 sayılı Kanunun "
                "5. maddesinin 3. fıkrası ne diyor?"
            ),

        "history": [],

        "expected_metadata": {
            "kanun_no": "6736",
            "madde": "5",
            "fikra": "3"
        },

        "expect_sources":
            True,

        "expected_document_id":
            "kanun_6736",

        "expected_temporal_mode":
            "neutral",

        "expected_temporal_scope":
            "document",

        "expected_query_date":
            None,

        "expected_source_temporal_result":
            "neutral",

        "expected_version_selection_status":
            "neutral",

        "expected_provision_status":
            "resolved",

        "expected_provision_scope":
            "neutral",

        "expected_provision_id":
            "kanun_6736_m5_f3",

        "expected_provision_match_type":
            "exact_fikra",

        "expected_failure_reason":
            None
    },


    # ========================================================
    # T02
    # ========================================================

    {
        "id": "T02",

        "name":
            "Bent sorusunda parent provision kullanılmalı",

        "runner":
            "normal",

        "question":
            (
                "6736 sayılı Kanunun "
                "5. maddesinin 3. fıkrasının "
                "a bendindeki KDV artırım oranları nelerdir?"
            ),

        "history": [],

        "expected_metadata": {
            "kanun_no": "6736",
            "madde": "5",
            "fikra": "3",
            "bent": "a"
        },

        "expect_sources":
            True,

        "expected_document_id":
            "kanun_6736",

        "expected_temporal_mode":
            "neutral",

        "expected_temporal_scope":
            "document",

        "expected_query_date":
            None,

        "expected_source_temporal_result":
            "neutral",

        "expected_version_selection_status":
            "neutral",

        "expected_provision_status":
            "resolved",

        "expected_provision_scope":
            "neutral",

        "expected_provision_id":
            "kanun_6736_m5_f3",

        "expected_provision_match_type":
            "parent_fikra",

        "expected_failure_reason":
            None
    },


    # ========================================================
    # T03
    # ========================================================

    {
        "id": "T03",

        "name":
            "Olmayan madde",

        "runner":
            "normal",

        "question":
            (
                "6736 sayılı Kanunun "
                "99. maddesi ne diyor?"
            ),

        "history": [],

        "expected_metadata": {
            "kanun_no": "6736",
            "madde": "99"
        },

        "expect_sources":
            False,

        "expected_document_id":
            None,

        "expected_temporal_mode":
            "neutral",

        "expected_temporal_scope":
            "document",

        "expected_query_date":
            None,

        "expected_provision_status":
            "not_evaluated",

        "expected_failure_reason":
            "explicit_reference_not_found",

        "expect_insufficient":
            True
    },


    # ========================================================
    # T04
    # ========================================================

    {
        "id": "T04",

        "name":
            "İndekste olmayan kanun",

        "runner":
            "normal",

        "question":
            (
                "213 sayılı Vergi Usul Kanununun "
                "359. maddesi ne diyor?"
            ),

        "history": [],

        "expected_metadata": {
            "kanun_no": "213",
            "madde": "359"
        },

        "expect_sources":
            False,

        "expected_document_id":
            None,

        "expected_temporal_mode":
            "neutral",

        "expected_temporal_scope":
            "document",

        "expected_query_date":
            None,

        "expected_provision_status":
            "not_evaluated",

        "expected_failure_reason":
            "explicit_reference_not_found",

        "expect_insufficient":
            True
    },


    # ========================================================
    # T05
    # ========================================================

    {
        "id": "T05",

        "name":
            "Kaynakta olmayan Danıştay yaklaşımı",

        "runner":
            "normal",

        "question":
            (
                "6736 sayılı Kanunun "
                "5. maddesinin 3. fıkrası hakkında "
                "Danıştay'ın yaklaşımı nedir?"
            ),

        "history": [],

        "expected_metadata": {
            "kanun_no": "6736",
            "madde": "5",
            "fikra": "3"
        },

        "expect_sources":
            True,

        "expected_document_id":
            "kanun_6736",

        "expected_temporal_mode":
            "neutral",

        "expected_temporal_scope":
            "document",

        "expected_query_date":
            None,

        "expected_provision_status":
            "resolved",

        "expected_provision_scope":
            "neutral",

        "expected_failure_reason":
            None,

        "expect_insufficient":
            True,

        "required_answer_any": [
            "danıştay",
            "yargı",
            "mevcut kaynak",
            "bulunm"
        ]
    },


    # ========================================================
    # T06
    # ========================================================

    {
        "id": "T06",

        "name":
            "Takip sorusu history ile çözülmeli",

        "runner":
            "normal",

        "question":
            "Peki b bendinde ne diyor?",

        "history": [

            {
                "role":
                    "user",

                "content":
                    (
                        "6736 sayılı Kanunun "
                        "5. maddesinin 3. fıkrası ne diyor?"
                    )
            },

            {
                "role":
                    "assistant",

                "content":
                    (
                        "6736 sayılı Kanunun "
                        "5. maddesinin 3. fıkrasını açıklamıştım."
                    )
            }
        ],

        "expected_metadata": {
            "kanun_no": "6736",
            "madde": "5",
            "fikra": "3",
            "bent": "b"
        },

        "expect_sources":
            True,

        "expected_document_id":
            "kanun_6736",

        "expected_temporal_mode":
            "neutral",

        "expected_temporal_scope":
            "document",

        "expected_query_date":
            None,

        "expected_provision_status":
            "resolved",

        "expected_provision_scope":
            "neutral",

        "expected_provision_id":
            "kanun_6736_m5_f3",

        "expected_provision_match_type":
            "parent_fikra",

        "expected_failure_reason":
            None
    },


    # ========================================================
    # T07
    # ========================================================

    {
        "id": "T07",

        "name":
            "Normal soru temporal neutral kalmalı",

        "runner":
            "normal",

        "question":
            (
                "6736 sayılı Kanunun "
                "5. maddesinin 3. fıkrası ne diyor?"
            ),

        "history": [],

        "expected_metadata": {
            "kanun_no": "6736",
            "madde": "5",
            "fikra": "3"
        },

        "expect_sources":
            True,

        "expected_document_id":
            "kanun_6736",

        "expected_temporal_mode":
            "neutral",

        "expected_temporal_scope":
            "document",

        "expected_query_date":
            None,

        "expected_source_temporal_result":
            "neutral",

        "expected_version_selection_status":
            "neutral",

        "expected_provision_status":
            "resolved",

        "expected_provision_scope":
            "neutral",

        "expected_failure_reason":
            None
    },


    # ========================================================
    # T08
    #
    # DOCUMENT CURRENT VALID
    #
    # AMA PROVISION FORMAL UNKNOWN
    # ========================================================

    {
        "id": "T08",

        "name":
            "Current document valid provision formal unknown olabilir",

        "runner":
            "normal",

        "question":
            (
                "6736 sayılı Kanunun "
                "5. maddesinin 3. fıkrası bugün yürürlükte mi?"
            ),

        "history": [],

        "expected_metadata": {
            "kanun_no": "6736",
            "madde": "5",
            "fikra": "3"
        },

        "expect_sources":
            True,

        "expected_document_id":
            "kanun_6736",

        "expected_temporal_mode":
            "current",

        "expected_temporal_scope":
            "document",

        "expected_query_date":
            None,

        "expected_source_temporal_result":
            "valid",

        "expected_temporal_score":
            1.0,

        "expected_version_selection_status":
            "selected",

        "expected_source_version_status":
            "selected",

        "expected_provision_status":
            "resolved",

        "expected_provision_scope":
            "formal_status",

        "expected_provision_formal_result":
            "unknown",

        "expected_provision_applicability_result":
            "not_applicable",

        "expected_provision_decision":
            "formal_unknown",

        "expected_failure_reason":
            None,

        "forbidden_answer_patterns": [
            "kesin olarak yürürlüktedir",
            "halen yürürlüktedir",
            "hâlen yürürlüktedir",
            "yürürlükten kaldırılmamıştır"
        ]
    },


    # ========================================================
    # T09
    # ========================================================

    {
        "id": "T09",

        "name":
            "2020 document valid ama provision formal unknown",

        "runner":
            "normal",

        "question":
            (
                "6736 sayılı Kanunun "
                "5. maddesinin 3. fıkrası "
                "2020 yılında geçerli miydi?"
            ),

        "history": [],

        "expected_metadata": {
            "kanun_no": "6736",
            "madde": "5",
            "fikra": "3"
        },

        "expect_sources":
            True,

        "expected_document_id":
            "kanun_6736",

        "expected_temporal_mode":
            "historical_date",

        "expected_temporal_scope":
            "document",

        "expected_query_date":
            "2020-01-01",

        "expected_source_temporal_result":
            "valid",

        "expected_temporal_score":
            1.0,

        "expected_version_selection_status":
            "selected",

        "expected_provision_status":
            "resolved",

        "expected_provision_scope":
            "formal_status",

        "expected_provision_formal_result":
            "unknown",

        "expected_provision_applicability_result":
            "not_applicable",

        "expected_provision_decision":
            "formal_unknown",

        "expected_failure_reason":
            None
    },


    # ========================================================
    # T10
    # ========================================================

    {
        "id": "T10",

        "name":
            "2021 tam tarih document valid provision formal unknown",

        "runner":
            "normal",

        "question":
            (
                "6736 sayılı Kanunun "
                "5. maddesinin 3. fıkrası "
                "01.06.2021 tarihinde geçerli miydi?"
            ),

        "history": [],

        "expected_metadata": {
            "kanun_no": "6736",
            "madde": "5",
            "fikra": "3"
        },

        "expect_sources":
            True,

        "expected_document_id":
            "kanun_6736",

        "expected_temporal_mode":
            "historical_date",

        "expected_temporal_scope":
            "document",

        "expected_query_date":
            "2021-06-01",

        "expected_source_temporal_result":
            "valid",

        "expected_temporal_score":
            1.0,

        "expected_version_selection_status":
            "selected",

        "expected_provision_status":
            "resolved",

        "expected_provision_scope":
            "formal_status",

        "expected_provision_formal_result":
            "unknown",

        "expected_provision_applicability_result":
            "not_applicable",

        "expected_provision_decision":
            "formal_unknown",

        "expected_failure_reason":
            None
    },


    # ========================================================
    # T11
    # ========================================================

    {
        "id": "T11",

        "name":
            "Current document version seçilmeli ve provision çözülmeli",

        "runner":
            "normal",

        "question":
            (
                "6736 sayılı Kanunun "
                "5. maddesinin 3. fıkrası bugün yürürlükte mi?"
            ),

        "history": [],

        "expected_metadata": {
            "kanun_no": "6736",
            "madde": "5",
            "fikra": "3"
        },

        "expect_sources":
            True,

        "expected_document_id":
            "kanun_6736",

        "expected_temporal_mode":
            "current",

        "expected_source_temporal_result":
            "valid",

        "expected_version_selection_status":
            "selected",

        "expected_version_group_status":
            "selected",

        "expected_source_version_status":
            "selected",

        "expected_provision_status":
            "resolved",

        "expected_provision_id":
            "kanun_6736_m5_f3",

        "expected_provision_version_id":
            "kanun_6736_m5_f3_v1",

        "expected_failure_reason":
            None
    },


    # ========================================================
    # T12
    # ========================================================

    {
        "id": "T12",

        "name":
            "Document version_conflict fail-closed",

        "runner":
            "synthetic_version_conflict",

        "question":
            (
                "6736 sayılı Kanunun "
                "5. maddesinin 3. fıkrası "
                "2020 yılında geçerli miydi?"
            ),

        "history": [],

        "expected_metadata": {
            "kanun_no": "6736",
            "madde": "5",
            "fikra": "3"
        },

        "expect_sources":
            False,

        "expected_temporal_mode":
            "historical_date",

        "expected_temporal_scope":
            "document",

        "expected_query_date":
            "2020-01-01",

        "expected_version_selection_status":
            "version_conflict",

        "expected_provision_status":
            "not_evaluated",

        "expected_failure_reason":
            "version_conflict",

        "required_answer_any": [
            "birden fazla",
            "otomatik sürüm seçimi yapmadı",
            "yanlış hukuki sürüm"
        ]
    },


    # ========================================================
    # T13
    # ========================================================

    {
        "id": "T13",

        "name":
            "Document version_unresolved tahmin yapmamalı",

        "runner":
            "synthetic_version_unresolved",

        "question":
            (
                "6736 sayılı Kanunun "
                "5. maddesinin 3. fıkrası "
                "2020 yılında geçerli miydi?"
            ),

        "history": [],

        "expected_metadata": {
            "kanun_no": "6736",
            "madde": "5",
            "fikra": "3"
        },

        "expect_sources":
            False,

        "expected_temporal_mode":
            "historical_date",

        "expected_temporal_scope":
            "document",

        "expected_query_date":
            "2020-01-01",

        "expected_version_selection_status":
            "version_unresolved",

        "expected_provision_status":
            "not_evaluated",

        "expected_failure_reason":
            "version_unresolved",

        "required_answer_any": [
            "birden fazla sürüm",
            "güvenilir biçimde belirlemeye yeterli değil",
            "tahmin yaparak"
        ]
    },


    # ========================================================
    # T14
    #
    # ESKİ V4 TESTİNİN YENİ HALİ
    #
    # Artık "doğrulanamıyor" beklemiyoruz.
    #
    # Complete verified windows var.
    #
    # Dolayısıyla bugün:
    #
    # NOT_APPLICABLE
    # ========================================================

    {
        "id": "T14",

        "name":
            "Bugünkü applicability deterministic not_applicable olmalı",

        "runner":
            "normal",

        "question":
            (
                "6736 sayılı Kanunun "
                "5. maddesinin 3. fıkrasındaki "
                "KDV artırımından bugün yararlanabilir miyim?"
            ),

        "history": [],

        "expected_metadata": {
            "kanun_no": "6736",
            "madde": "5",
            "fikra": "3"
        },

        "expect_sources":
            True,

        "expected_temporal_mode":
            "current",

        "expected_source_temporal_result":
            "valid",

        "expected_temporal_score":
            1.0,

        "expected_version_selection_status":
            "selected",

        "expected_provision_status":
            "resolved",

        "expected_provision_scope":
            "applicability",

        "expected_provision_formal_result":
            "unknown",

        "expected_provision_applicability_result":
            "not_applicable",

        "expected_provision_decision":
            "applicability_not_applicable",

        "expected_failure_reason":
            None,

        "required_answer_any": [
            "not_applicable",
            "başvuru süresi sona ermiş",
            "pencerelerinin dışındadır",
            "zaman penceresi"
        ],

        "forbidden_answer_patterns": [
            "mülgadır.",
            "kesin olarak mülgadır"
        ]
    },


    # ========================================================
    # T15
    #
    # NULL REPEAL / FORMAL UNKNOWN
    # ========================================================

    {
        "id": "T15",

        "name":
            "Formal unknown kesin mülga sonucu üretmemeli",

        "runner":
            "normal",

        "question":
            (
                "6736 sayılı Kanunun "
                "5. maddesinin 3. fıkrası "
                "bugün yürürlükten kaldırılmış durumda mı?"
            ),

        "history": [],

        "expected_metadata": {
            "kanun_no": "6736",
            "madde": "5",
            "fikra": "3"
        },

        "expect_sources":
            True,

        "expected_temporal_mode":
            "current",

        "expected_source_temporal_result":
            "valid",

        "expected_provision_status":
            "resolved",

        "expected_provision_scope":
            "formal_status",

        "expected_provision_formal_result":
            "unknown",

        "expected_provision_applicability_result":
            "not_applicable",

        "expected_provision_decision":
            "formal_unknown",

        "expected_failure_reason":
            None,

        "required_answer_any": [
            "formal",
            "unknown",
            "doğrulanmış değildir",
            "kanıtlamaz"
        ],

        "forbidden_answer_patterns": [
            "yürürlükten kaldırılmamıştır",
            "yürürlükten kaldırılmış değildir",
            "yürürlüktedir.",
            "mülga değildir.",
            "kesin olarak yürürlüktedir"
        ]
    },


    # ========================================================
    # T16
    #
    # 2016/9385 UZATMA PENCERESİ
    # ========================================================

    {
        "id": "T16",

        "name":
            "10.11.2016 uzatma penceresinde applicable olmalı",

        "runner":
            "normal",

        "question":
            (
                "6736 sayılı Kanunun 5. maddesinin "
                "3. fıkrasındaki KDV artırımından "
                "10.11.2016 tarihinde yararlanılabilir miydi?"
            ),

        "history": [],

        "expected_metadata": {
            "kanun_no": "6736",
            "madde": "5",
            "fikra": "3"
        },

        "expect_sources":
            True,

        "expected_document_id":
            "kanun_6736",

        "expected_temporal_mode":
            "historical_date",

        "expected_temporal_scope":
            "document",

        "expected_query_date":
            "2016-11-10",

        "expected_source_temporal_result":
            "valid",

        "expected_version_selection_status":
            "selected",

        "expected_provision_status":
            "resolved",

        "expected_provision_scope":
            "applicability",

        "expected_provision_id":
            "kanun_6736_m5_f3",

        "expected_provision_match_type":
            "exact_fikra",

        "expected_provision_version_id":
            "kanun_6736_m5_f3_v1",

        "expected_verification_state":
            "partially_verified",

        "expected_provision_formal_result":
            "unknown",

        "expected_provision_applicability_result":
            "applicable",

        "expected_provision_decision":
            "applicability_applicable",

        "expected_matched_window":
            "application_extension_2016_9385",

        "expected_failure_reason":
            None,

        "required_answer_any": [
            "applicable",
            "application_extension_2016_9385"
        ]
    },


    # ========================================================
    # T17
    #
    # 2020
    #
    # FORMAL UNKNOWN
    # APPLICABILITY NOT_APPLICABLE
    # ========================================================

    {
        "id": "T17",

        "name":
            "2020 applicability not_applicable formal unknown",

        "runner":
            "normal",

        "question":
            (
                "6736 sayılı Kanunun 5. maddesinin "
                "3. fıkrasındaki KDV artırımından "
                "2020 yılında yararlanılabilir miydi?"
            ),

        "history": [],

        "expected_metadata": {
            "kanun_no": "6736",
            "madde": "5",
            "fikra": "3"
        },

        "expect_sources":
            True,

        "expected_temporal_mode":
            "historical_date",

        "expected_query_date":
            "2020-01-01",

        "expected_source_temporal_result":
            "valid",

        "expected_provision_status":
            "resolved",

        "expected_provision_scope":
            "applicability",

        "expected_provision_formal_result":
            "unknown",

        "expected_provision_applicability_result":
            "not_applicable",

        "expected_provision_decision":
            "applicability_not_applicable",

        "expected_failure_reason":
            None,

        "required_answer_any": [
            "not_applicable",
            "pencerelerinin dışındadır",
            "başvuru süresi sona ermiş"
        ],

        "forbidden_answer_patterns": [
            "6736 sayılı kanun m.5/3 mülgadır.",
            "hüküm mülgadır."
        ]
    },


    # ========================================================
    # T18
    #
    # AYNI TARİH
    #
    # AMA SORU FORMAL
    # ========================================================

    {
        "id": "T18",

        "name":
            "2020 mülga sorusunda formal unknown korunmalı",

        "runner":
            "normal",

        "question":
            (
                "6736 sayılı Kanunun 5. maddesinin "
                "3. fıkrası 2020 yılında mülga mıydı?"
            ),

        "history": [],

        "expected_metadata": {
            "kanun_no": "6736",
            "madde": "5",
            "fikra": "3"
        },

        "expect_sources":
            True,

        "expected_temporal_mode":
            "historical_date",

        "expected_query_date":
            "2020-01-01",

        "expected_source_temporal_result":
            "valid",

        "expected_provision_status":
            "resolved",

        "expected_provision_scope":
            "formal_status",

        "expected_provision_formal_result":
            "unknown",

        "expected_provision_applicability_result":
            "not_applicable",

        "expected_provision_decision":
            "formal_unknown",

        "expected_failure_reason":
            None,

        "required_answer_any": [
            "formal",
            "unknown",
            "doğrulanmış değildir"
        ],

        "forbidden_answer_patterns": [
            "mülga değildi",
            "mülga değildir",
            "mülgadır",
            "kesin olarak yürürlükte"
        ]
    },


    # ========================================================
    # T19
    #
    # UZATMA SONRASI
    #
    # 25.11.2016 sonrası
    # ========================================================

    {
        "id": "T19",

        "name":
            "01.12.2016 uzatma sonrası not_applicable olmalı",

        "runner":
            "normal",

        "question":
            (
                "6736 sayılı Kanunun 5. maddesinin "
                "3. fıkrasındaki KDV artırımından "
                "01.12.2016 tarihinde yararlanılabilir miydi?"
            ),

        "history": [],

        "expected_metadata": {
            "kanun_no": "6736",
            "madde": "5",
            "fikra": "3"
        },

        "expect_sources":
            True,

        "expected_temporal_mode":
            "historical_date",

        "expected_query_date":
            "2016-12-01",

        "expected_source_temporal_result":
            "valid",

        "expected_provision_status":
            "resolved",

        "expected_provision_scope":
            "applicability",

        "expected_provision_formal_result":
            "unknown",

        "expected_provision_applicability_result":
            "not_applicable",

        "expected_provision_decision":
            "applicability_not_applicable",

        "expected_failure_reason":
            None,

        "required_answer_any": [
            "not_applicable",
            "pencerelerinin dışındadır"
        ]
    }
]


# ============================================================
# HELPERS
# ============================================================

def normalize(value):
    if value is None:
        return None

    return str(
        value
    ).strip().lower()


def safe_list(value):
    if value is None:
        return []

    if isinstance(
        value,
        list
    ):
        return value

    return [value]


# ============================================================
# METADATA
# ============================================================

def check_metadata(
    actual,
    expected
):
    errors = []

    for key, expected_value in expected.items():
        actual_value = actual.get(
            key
        )

        if normalize(
            actual_value
        ) != normalize(
            expected_value
        ):
            errors.append(
                f"{key}: "
                f"beklenen={expected_value}, "
                f"gerçek={actual_value}"
            )

    return errors


# ============================================================
# SOURCES
# ============================================================

def check_sources(
    sources,
    expect_sources,
    expected_document_id
):
    errors = []

    if expect_sources:
        if not sources:
            errors.append(
                "Kaynak bekleniyordu ancak kaynak bulunamadı."
            )

    else:
        if sources:
            errors.append(
                "Kaynak beklenmiyordu ancak "
                f"{len(sources)} kaynak döndü."
            )

    if (
        expected_document_id
        and sources
    ):
        if not any(
            source.get(
                "document_id"
            )
            == expected_document_id
            for source in sources
        ):
            errors.append(
                "Beklenen document_id bulunamadı: "
                f"{expected_document_id}"
            )

    return errors


# ============================================================
# INSUFFICIENT
# ============================================================

def answer_mentions_insufficient(
    answer
):
    text = normalize(
        answer
    ) or ""

    patterns = [
        "yeterli değil",
        "yetersiz",
        "bulunamadı",
        "mevcut kaynak",
        "doğrulanam",
        "kaynaklarda yer alm",
        "yargı kararı bulun",
        "danıştay kararı bulun",
    ]

    return any(
        pattern in text
        for pattern in patterns
    )


def check_insufficient(
    answer,
    expected
):
    if expected is not True:
        return []

    if answer_mentions_insufficient(
        answer
    ):
        return []

    return [
        "Kaynak/veri yetersizliğinin belirtilmesi bekleniyordu."
    ]


# ============================================================
# TEMPORAL
# ============================================================

def check_temporal(
    temporal,
    expected_mode=None,
    expected_scope=None,
    expected_date=None
):
    errors = []

    if (
        expected_mode is not None
        and normalize(
            temporal.get(
                "mode"
            )
        )
        != normalize(
            expected_mode
        )
    ):
        errors.append(
            "Temporal mode hatalı: "
            f"beklenen={expected_mode}, "
            f"gerçek={temporal.get('mode')}"
        )

    if (
        expected_scope is not None
        and normalize(
            temporal.get(
                "scope"
            )
        )
        != normalize(
            expected_scope
        )
    ):
        errors.append(
            "Temporal scope hatalı: "
            f"beklenen={expected_scope}, "
            f"gerçek={temporal.get('scope')}"
        )

    actual_date = temporal.get(
        "query_date"
    )

    if normalize(
        actual_date
    ) != normalize(
        expected_date
    ):
        errors.append(
            "Temporal query_date hatalı: "
            f"beklenen={expected_date}, "
            f"gerçek={actual_date}"
        )

    return errors


# ============================================================
# SOURCE TEMPORAL
# ============================================================

def check_source_temporal_result(
    sources,
    expected
):
    if expected is None:
        return []

    errors = []

    if not sources:
        return [
            "Source temporal sonucu kontrolü için kaynak yok."
        ]

    for index, source in enumerate(
        sources,
        start=1
    ):
        actual = source.get(
            "temporal_result"
        )

        if normalize(
            actual
        ) != normalize(
            expected
        ):
            errors.append(
                f"Kaynak {index} temporal_result hatalı: "
                f"beklenen={expected}, gerçek={actual}"
            )

    return errors


def check_temporal_score(
    sources,
    expected
):
    if expected is None:
        return []

    errors = []

    for index, source in enumerate(
        sources,
        start=1
    ):
        actual = source.get(
            "temporal_score"
        )

        try:
            actual = float(
                actual
            )

        except (
            TypeError,
            ValueError
        ):
            errors.append(
                f"Kaynak {index} temporal_score geçersiz: {actual}"
            )
            continue

        if abs(
            actual
            - float(
                expected
            )
        ) > 0.0001:
            errors.append(
                f"Kaynak {index} temporal_score hatalı: "
                f"beklenen={expected}, gerçek={actual}"
            )

    return errors


# ============================================================
# DOCUMENT VERSION
# ============================================================

def check_version_selection(
    version_selection,
    expected_status=None,
    expected_group_status=None
):
    errors = []

    if expected_status is not None:
        actual = version_selection.get(
            "selection_status"
        )

        if normalize(
            actual
        ) != normalize(
            expected_status
        ):
            errors.append(
                "Version selection status hatalı: "
                f"beklenen={expected_status}, gerçek={actual}"
            )

    if expected_group_status is not None:
        groups = version_selection.get(
            "groups",
            []
        )

        statuses = [
            normalize(
                group.get(
                    "status"
                )
            )
            for group in groups
        ]

        if normalize(
            expected_group_status
        ) not in statuses:
            errors.append(
                "Beklenen version group status bulunamadı: "
                f"{expected_group_status}; gerçek={statuses}"
            )

    return errors


def check_source_version_status(
    sources,
    expected
):
    if expected is None:
        return []

    errors = []

    for index, source in enumerate(
        sources,
        start=1
    ):
        actual = source.get(
            "version_selection_status"
        )

        if normalize(
            actual
        ) != normalize(
            expected
        ):
            errors.append(
                f"Kaynak {index} version_selection_status hatalı: "
                f"beklenen={expected}, gerçek={actual}"
            )

    return errors


# ============================================================
# PROVISION
# ============================================================

def check_provision(
    provision,
    test_case
):
    errors = []

    expected_status = test_case.get(
        "expected_provision_status"
    )

    if expected_status is not None:
        actual = provision.get(
            "status"
        )

        if normalize(
            actual
        ) != normalize(
            expected_status
        ):
            errors.append(
                "Provision status hatalı: "
                f"beklenen={expected_status}, gerçek={actual}"
            )

    expected_scope = test_case.get(
        "expected_provision_scope"
    )

    if expected_scope is not None:
        actual = provision.get(
            "question_scope"
        )

        if normalize(
            actual
        ) != normalize(
            expected_scope
        ):
            errors.append(
                "Provision question_scope hatalı: "
                f"beklenen={expected_scope}, gerçek={actual}"
            )

    resolution = provision.get(
        "resolution",
        {}
    )

    expected_id = test_case.get(
        "expected_provision_id"
    )

    if expected_id is not None:
        actual = resolution.get(
            "provision_id"
        )

        if normalize(
            actual
        ) != normalize(
            expected_id
        ):
            errors.append(
                "Provision ID hatalı: "
                f"beklenen={expected_id}, gerçek={actual}"
            )

    expected_match = test_case.get(
        "expected_provision_match_type"
    )

    if expected_match is not None:
        actual = resolution.get(
            "match_type"
        )

        if normalize(
            actual
        ) != normalize(
            expected_match
        ):
            errors.append(
                "Provision match_type hatalı: "
                f"beklenen={expected_match}, gerçek={actual}"
            )

    expected_version_id = test_case.get(
        "expected_provision_version_id"
    )

    if expected_version_id is not None:
        actual = provision.get(
            "provision_version_id"
        )

        if normalize(
            actual
        ) != normalize(
            expected_version_id
        ):
            errors.append(
                "Provision version ID hatalı: "
                f"beklenen={expected_version_id}, gerçek={actual}"
            )

    expected_verification = test_case.get(
        "expected_verification_state"
    )

    if expected_verification is not None:
        actual = provision.get(
            "verification_state"
        )

        if normalize(
            actual
        ) != normalize(
            expected_verification
        ):
            errors.append(
                "Provision verification_state hatalı: "
                f"beklenen={expected_verification}, gerçek={actual}"
            )

    policy = provision.get(
        "policy"
    )

    if not isinstance(
        policy,
        dict
    ):
        policy = {}

    formal = policy.get(
        "formal",
        {}
    )

    applicability = policy.get(
        "applicability",
        {}
    )

    expected_formal = test_case.get(
        "expected_provision_formal_result"
    )

    if expected_formal is not None:
        actual = formal.get(
            "result"
        )

        if normalize(
            actual
        ) != normalize(
            expected_formal
        ):
            errors.append(
                "Provision formal result hatalı: "
                f"beklenen={expected_formal}, gerçek={actual}"
            )

    expected_applicability = test_case.get(
        "expected_provision_applicability_result"
    )

    if expected_applicability is not None:
        actual = applicability.get(
            "result"
        )

        if normalize(
            actual
        ) != normalize(
            expected_applicability
        ):
            errors.append(
                "Provision applicability result hatalı: "
                f"beklenen={expected_applicability}, gerçek={actual}"
            )

    expected_decision = test_case.get(
        "expected_provision_decision"
    )

    if expected_decision is not None:
        actual = policy.get(
            "decision_result"
        )

        if normalize(
            actual
        ) != normalize(
            expected_decision
        ):
            errors.append(
                "Provision decision_result hatalı: "
                f"beklenen={expected_decision}, gerçek={actual}"
            )

    expected_window = test_case.get(
        "expected_matched_window"
    )

    if expected_window is not None:
        actual_windows = applicability.get(
            "matched_window_ids",
            []
        )

        normalized_windows = [
            normalize(
                value
            )
            for value in actual_windows
        ]

        if normalize(
            expected_window
        ) not in normalized_windows:
            errors.append(
                "Beklenen applicability window bulunamadı: "
                f"{expected_window}; gerçek={actual_windows}"
            )

    return errors


# ============================================================
# FAILURE
# ============================================================

def check_failure_reason(
    actual,
    expected
):
    if normalize(
        actual
    ) == normalize(
        expected
    ):
        return []

    return [
        "retrieval_failure_reason hatalı: "
        f"beklenen={expected}, gerçek={actual}"
    ]


# ============================================================
# ANSWER PATTERNS
# ============================================================

def check_required_answer_any(
    answer,
    patterns
):
    patterns = safe_list(
        patterns
    )

    if not patterns:
        return []

    text = normalize(
        answer
    ) or ""

    if any(
        normalize(
            pattern
        ) in text
        for pattern in patterns
    ):
        return []

    return [
        "Cevap beklenen ifadelerden hiçbirini içermiyor: "
        f"{patterns}"
    ]


def check_forbidden_answer_patterns(
    answer,
    patterns
):
    patterns = safe_list(
        patterns
    )

    if not patterns:
        return []

    text = normalize(
        answer
    ) or ""

    errors = []

    for pattern in patterns:
        if normalize(
            pattern
        ) in text:
            errors.append(
                "Cevap yasaklanan / aşırı kesin ifadeyi içeriyor: "
                f"'{pattern}'"
            )

    return errors


# ============================================================
# SYNTHETIC DOCUMENT VERSION FAILURES
# ============================================================

def build_synthetic_version_selection(
    status
):
    if status == "version_conflict":
        return {
            "selection_status":
                "version_conflict",

            "failure_reason":
                "version_conflict",

            "has_conflict":
                True,

            "groups": [
                {
                    "group_key":
                        "Kanun:6736",

                    "status":
                        "version_conflict",

                    "selected_document_ids":
                        [],

                    "valid_document_ids": [
                        "kanun_6736_v1",
                        "kanun_6736_v2"
                    ],

                    "unknown_document_ids":
                        [],

                    "invalid_document_ids":
                        [],

                    "neutral_document_ids":
                        [],

                    "message":
                        "Synthetic document version conflict."
                }
            ]
        }

    if status == "version_unresolved":
        return {
            "selection_status":
                "version_unresolved",

            "failure_reason":
                "version_unresolved",

            "has_conflict":
                True,

            "groups": [
                {
                    "group_key":
                        "Kanun:6736",

                    "status":
                        "version_unresolved",

                    "selected_document_ids":
                        [],

                    "valid_document_ids":
                        [],

                    "unknown_document_ids": [
                        "kanun_6736_v1",
                        "kanun_6736_v2"
                    ],

                    "invalid_document_ids":
                        [],

                    "neutral_document_ids":
                        [],

                    "message":
                        "Synthetic document version unresolved."
                }
            ]
        }

    raise ValueError(
        f"Geçersiz synthetic status: {status}"
    )


def run_synthetic_version_failure(
    test_case,
    failure_status
):
    original = (
        rag_module.retrieve_candidates
    )

    synthetic_selection = (
        build_synthetic_version_selection(
            failure_status
        )
    )

    def synthetic_retrieve_candidates(
        search_query,
        metadata,
        temporal_context
    ):
        return {
            "candidates":
                [],

            "failure_reason":
                failure_status,

            "retriever_failure_reason":
                failure_status,

            "version_selection":
                copy.deepcopy(
                    synthetic_selection
                )
        }

    try:
        rag_module.retrieve_candidates = (
            synthetic_retrieve_candidates
        )

        return rag_module.answer_question(
            question=
                test_case[
                    "question"
                ],

            history=
                test_case.get(
                    "history",
                    []
                )
        )

    finally:
        rag_module.retrieve_candidates = (
            original
        )


# ============================================================
# EXECUTION
# ============================================================

def execute_test_case(
    test_case
):
    runner = test_case.get(
        "runner",
        "normal"
    )

    if runner == "normal":
        return rag_module.answer_question(
            question=
                test_case[
                    "question"
                ],

            history=
                test_case.get(
                    "history",
                    []
                )
        )

    if runner == "synthetic_version_conflict":
        return run_synthetic_version_failure(
            test_case,
            "version_conflict"
        )

    if runner == "synthetic_version_unresolved":
        return run_synthetic_version_failure(
            test_case,
            "version_unresolved"
        )

    raise ValueError(
        f"Bilinmeyen runner: {runner}"
    )


# ============================================================
# OUTPUT
# ============================================================

def print_sources(
    sources
):
    if not sources:
        print(
            "Kaynak yok."
        )
        return

    for index, source in enumerate(
        sources,
        start=1
    ):
        print(
            f"\nKaynak {index}:"
        )

        print(
            "  Document:",
            source.get(
                "document_id"
            )
        )

        print(
            "  Kanun:",
            source.get(
                "kanun_no"
            )
        )

        print(
            "  Madde:",
            source.get(
                "madde"
            )
        )

        print(
            "  Fıkra:",
            source.get(
                "fikra"
            )
        )

        print(
            "  Bent:",
            source.get(
                "bent"
            )
        )

        print(
            "  Status:",
            source.get(
                "status"
            )
        )

        print(
            "  Version:",
            source.get(
                "version"
            )
        )

        print(
            "  Version selection:",
            source.get(
                "version_selection_status"
            )
        )

        print(
            "  Temporal result:",
            source.get(
                "temporal_result"
            )
        )

        print(
            "  Temporal score:",
            source.get(
                "temporal_score"
            )
        )


def print_provision(
    provision
):
    print(
        "\nPROVISION:"
    )

    print(
        "  Status:",
        provision.get(
            "status"
        )
    )

    print(
        "  Question scope:",
        provision.get(
            "question_scope"
        )
    )

    resolution = provision.get(
        "resolution",
        {}
    )

    print(
        "  Provision ID:",
        resolution.get(
            "provision_id"
        )
    )

    print(
        "  Match type:",
        resolution.get(
            "match_type"
        )
    )

    print(
        "  Version ID:",
        provision.get(
            "provision_version_id"
        )
    )

    print(
        "  Verification:",
        provision.get(
            "verification_state"
        )
    )

    policy = provision.get(
        "policy"
    )

    if not isinstance(
        policy,
        dict
    ):
        print(
            "  Policy: None"
        )
        return

    formal = policy.get(
        "formal",
        {}
    )

    applicability = policy.get(
        "applicability",
        {}
    )

    print(
        "  Target date:",
        policy.get(
            "target_date"
        )
    )

    print(
        "  Formal:",
        formal.get(
            "result"
        )
    )

    print(
        "  Applicability:",
        applicability.get(
            "result"
        )
    )

    print(
        "  Matched windows:",
        applicability.get(
            "matched_window_ids"
        )
    )

    print(
        "  Decision:",
        policy.get(
            "decision_result"
        )
    )


# ============================================================
# RUN SINGLE TEST
# ============================================================

def run_test(
    test_case
):
    print(
        "\n\n======================================"
    )

    print(
        f"{test_case['id']} - "
        f"{test_case['name']}"
    )

    print(
        "======================================"
    )

    print(
        "\nSORU:"
    )

    print(
        test_case[
            "question"
        ]
    )

    try:
        result = execute_test_case(
            test_case
        )

    except Exception as error:
        print(
            "\nTEST ÇALIŞTIRMA HATASI:"
        )

        print(
            error
        )

        return {
            "id":
                test_case[
                    "id"
                ],

            "name":
                test_case[
                    "name"
                ],

            "passed":
                False,

            "errors": [
                str(
                    error
                )
            ]
        }

    metadata = result.get(
        "metadata",
        {}
    )

    temporal = result.get(
        "temporal",
        {}
    )

    version_selection = result.get(
        "version_selection",
        {}
    )

    provision = result.get(
        "provision",
        {}
    )

    sources = result.get(
        "sources",
        []
    )

    answer = result.get(
        "answer",
        ""
    )

    failure_reason = result.get(
        "retrieval_failure_reason"
    )

    # ========================================================
    # PRINT
    # ========================================================

    print(
        "\nARAMA SORGUSU:"
    )

    print(
        result.get(
            "search_query"
        )
    )

    print(
        "\nMETADATA:"
    )

    print(
        metadata
    )

    print(
        "\nTEMPORAL:"
    )

    print(
        temporal
    )

    print(
        "\nVERSION:"
    )

    print(
        version_selection.get(
            "selection_status"
        )
    )

    print_provision(
        provision
    )

    print(
        "\nFAILURE:"
    )

    print(
        failure_reason
    )

    print(
        "\nKAYNAK SAYISI:"
    )

    print(
        len(
            sources
        )
    )

    print_sources(
        sources
    )

    print(
        "\nCEVAP:"
    )

    print(
        answer
    )

    # ========================================================
    # CHECK
    # ========================================================

    errors = []

    errors.extend(
        check_metadata(
            metadata,
            test_case.get(
                "expected_metadata",
                {}
            )
        )
    )

    errors.extend(
        check_sources(
            sources=
                sources,

            expect_sources=
                test_case.get(
                    "expect_sources",
                    False
                ),

            expected_document_id=
                test_case.get(
                    "expected_document_id"
                )
        )
    )

    errors.extend(
        check_insufficient(
            answer=
                answer,

            expected=
                test_case.get(
                    "expect_insufficient"
                )
        )
    )

    errors.extend(
        check_temporal(
            temporal=
                temporal,

            expected_mode=
                test_case.get(
                    "expected_temporal_mode"
                ),

            expected_scope=
                test_case.get(
                    "expected_temporal_scope"
                ),

            expected_date=
                test_case.get(
                    "expected_query_date"
                )
        )
    )

    errors.extend(
        check_source_temporal_result(
            sources,
            test_case.get(
                "expected_source_temporal_result"
            )
        )
    )

    errors.extend(
        check_temporal_score(
            sources,
            test_case.get(
                "expected_temporal_score"
            )
        )
    )

    errors.extend(
        check_version_selection(
            version_selection=
                version_selection,

            expected_status=
                test_case.get(
                    "expected_version_selection_status"
                ),

            expected_group_status=
                test_case.get(
                    "expected_version_group_status"
                )
        )
    )

    errors.extend(
        check_source_version_status(
            sources,
            test_case.get(
                "expected_source_version_status"
            )
        )
    )

    errors.extend(
        check_provision(
            provision=
                provision,

            test_case=
                test_case
        )
    )

    errors.extend(
        check_failure_reason(
            actual=
                failure_reason,

            expected=
                test_case.get(
                    "expected_failure_reason"
                )
        )
    )

    errors.extend(
        check_required_answer_any(
            answer=
                answer,

            patterns=
                test_case.get(
                    "required_answer_any"
                )
        )
    )

    errors.extend(
        check_forbidden_answer_patterns(
            answer=
                answer,

            patterns=
                test_case.get(
                    "forbidden_answer_patterns"
                )
        )
    )

    passed = (
        len(
            errors
        )
        == 0
    )

    print(
        "\nTEST SONUCU:"
    )

    print(
        "PASS"
        if passed
        else "FAIL"
    )

    if errors:
        print(
            "\nHATALAR:"
        )

        for error in errors:
            print(
                "-",
                error
            )

    return {
        "id":
            test_case[
                "id"
            ],

        "name":
            test_case[
                "name"
            ],

        "passed":
            passed,

        "errors":
            errors
    }


# ============================================================
# RUN ALL
# ============================================================

def run_all_tests():
    print(
        "\n======================================"
    )

    print(
        " VERGİ AI - RAG QUALITY EVALUATION V5"
    )

    print(
        "======================================"
    )

    print(
        "RAG version:",
        getattr(
            rag_module,
            "RAG_VERSION",
            "unknown"
        )
    )

    print(
        "\nTest kapsamı:"
    )

    print(
        "- T01-T06: Basic Legal RAG"
    )

    print(
        "- T07-T11: Document Temporal + Version"
    )

    print(
        "- T12-T13: Document Version Fail-Closed"
    )

    print(
        "- T14-T15: Legal Safety"
    )

    print(
        "- T16-T19: Provision / Applicability"
    )

    results = []

    for test_case in TEST_CASES:
        results.append(
            run_test(
                test_case
            )
        )

    passed_count = sum(
        1
        for result in results
        if result[
            "passed"
        ]
    )

    failed_count = (
        len(
            results
        )
        - passed_count
    )

    print(
        "\n\n======================================"
    )

    print(
        " TEST ÖZETİ"
    )

    print(
        "======================================"
    )

    print(
        "Toplam test:",
        len(
            results
        )
    )

    print(
        "PASS:",
        passed_count
    )

    print(
        "FAIL:",
        failed_count
    )

    print(
        "\nTESTLER:"
    )

    for result in results:
        print(
            f"{result['id']}:",
            (
                "PASS"
                if result[
                    "passed"
                ]
                else "FAIL"
            )
        )

    if failed_count:
        print(
            "\n======================================"
        )

        print(
            " FAIL DETAYLARI"
        )

        print(
            "======================================"
        )

        for result in results:
            if result[
                "passed"
            ]:
                continue

            print(
                f"\n{result['id']} - "
                f"{result['name']}"
            )

            for error in result[
                "errors"
            ]:
                print(
                    "-",
                    error
                )

    print(
        "\n======================================"
    )

    return results


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    run_all_tests()