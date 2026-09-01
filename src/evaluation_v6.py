# ============================================================
# VERGİ AI - RAG QUALITY EVALUATION V6
#
# BASE:
#   Evaluation V5 T01-T19
#
# NEW:
#   T20-T24 Provision Version Selection Integration
#
#
# AMAÇ:
#
# Provision Version Policy V1'in yalnızca kendi unit
# testlerinde değil, RAG V3.5 uçtan uca akışında da
# doğru çalıştığını doğrulamak.
#
#
# TESTLER:
#
# T20
#   1 valid + 1 invalid
#   → valid provision version seçilmeli
#
# T21
#   2 valid
#   → version_conflict
#   → FAIL CLOSED
#
# T22
#   2 unknown
#   → version_unresolved
#   → FAIL CLOSED
#
# T23
#   tüm versions invalid
#   → no_valid_version
#   → FAIL CLOSED
#
# T24
#   tek unknown
#   → kullanılabilir
#   → AMA valid ilan edilmez
#
#
# KRİTİK PRENSİP:
#
# WRONG PROVISION VERSION
#           >
# NO PROVISION VERSION
#
# ============================================================


import copy

import evaluation as base_evaluation
import rag as rag_module


# ============================================================
# VERSION
# ============================================================

EVALUATION_VERSION = "6"


# ============================================================
# NORMALIZE
# ============================================================

def normalize(value):
    if value is None:
        return None

    value = str(
        value
    ).strip().lower()

    if not value:
        return None

    return value


# ============================================================
# ASSERT
# ============================================================

def assert_equal(
    actual,
    expected,
    message,
):
    if normalize(
        actual
    ) != normalize(
        expected
    ):
        raise AssertionError(
            f"{message} | "
            f"beklenen={expected}, "
            f"gerçek={actual}"
        )


def assert_in(
    value,
    values,
    message,
):
    normalized_value = normalize(
        value
    )

    normalized_values = [
        normalize(
            item
        )
        for item in values
    ]

    if normalized_value not in normalized_values:
        raise AssertionError(
            f"{message} | "
            f"beklenenlerden biri={values}, "
            f"gerçek={value}"
        )


def assert_contains_any(
    text,
    patterns,
    message,
):
    normalized_text = (
        normalize(
            text
        )
        or ""
    )

    for pattern in patterns:
        normalized_pattern = (
            normalize(
                pattern
            )
            or ""
        )

        if normalized_pattern in normalized_text:
            return

    raise AssertionError(
        f"{message} | "
        f"aranan={patterns}"
    )


def assert_not_contains(
    text,
    patterns,
    message,
):
    normalized_text = (
        normalize(
            text
        )
        or ""
    )

    for pattern in patterns:
        normalized_pattern = (
            normalize(
                pattern
            )
            or ""
        )

        if (
            normalized_pattern
            and normalized_pattern
            in normalized_text
        ):
            raise AssertionError(
                f"{message} | "
                f"yasak ifade={pattern}"
            )


# ============================================================
# SYNTHETIC PROVISION BUILDER
#
# Bu kayıtlar data/provisions.json'a yazılmaz.
#
# Sadece RAG integration regression testlerinde kullanılır.
# ============================================================

def build_synthetic_provision(
    version_id,
    formal_verified,
    formal_status,
    valid_from=None,
    valid_through=None,
    repeal_effective_date=None,
):
    return {
        "provision_id":
            "kanun_6736_m5_f3",

        "provision_version_id":
            version_id,

        "document_id":
            "kanun_6736",

        "enabled":
            True,

        "verification_state":
            (
                "verified"
                if formal_verified
                else "unverified"
            ),

        "locator": {
            "madde":
                "5",

            "fikra":
                "3",

            "bent":
                None,
        },

        "formal": {
            "verified":
                formal_verified,

            "status":
                formal_status,

            "valid_from":
                valid_from,

            "valid_through":
                valid_through,

            "repeal_effective_date":
                repeal_effective_date,

            "evidence":
                [],
        },

        "applicability": {
            "windows_complete":
                False,

            "windows_complete_verified":
                False,

            "completion_evidence":
                [],

            "windows":
                [],

            "notes":
                None,
        },

        "subject_periods":
            [],

        "relations":
            [],

        "notes":
            "Synthetic Evaluation V6 provision.",
    }


# ============================================================
# SYNTHETIC DOCUMENT SOURCE
#
# Provision Version entegrasyonunu test ederken retrieval
# katmanını tekrar test etmiyoruz.
#
# Retrieval zaten T01-T19 ile korunuyor.
#
# Böylece T20-T24:
#
# - hızlı
# - deterministik
# - LLM reranker'dan bağımsız
#
# çalışır.
# ============================================================

def build_synthetic_document_source(
    temporal_mode,
    query_date,
):
    return {
        "document_id":
            "kanun_6736",

        "chunk_id":
            "synthetic_6736_m5_f3",

        "belge_turu":
            "Kanun",

        "title":
            (
                "Bazı Alacakların Yeniden "
                "Yapılandırılmasına İlişkin Kanun"
            ),

        "short_title":
            "6736 sayılı Kanun",

        "kanun_no":
            "6736",

        "document_number":
            "6736",

        "madde":
            "5",

        "fikra":
            "3",

        "bent":
            None,

        "page":
            1,

        "source":
            "synthetic",

        "kaynak_kurum":
            "Synthetic Evaluation V6",

        "official_source":
            True,

        "source_url":
            None,

        "status":
            "active",

        "version":
            "1",

        "previous_version":
            None,

        "next_version":
            None,

        "version_selection_status":
            "selected",

        "version_group_status":
            "selected",

        "resmi_gazete_tarihi":
            "2016-08-19",

        "resmi_gazete_sayisi":
            "29806",

        "yayin_tarihi":
            "2016-08-19",

        "yururluk_tarihi":
            "2016-08-19",

        "gecerlilik_baslangici":
            None,

        "gecerlilik_sonu":
            None,

        "mulga_tarihi":
            None,

        "temporal_mode":
            temporal_mode,

        "query_date":
            query_date,

        "temporal_result":
            "valid",

        "temporal_score":
            1.0,

        "authority_level":
            "primary_binding",

        "semantic_score":
            1.0,

        "metadata_score":
            1.0,

        "final_score":
            1.0,

        "text":
            (
                "Synthetic source used only for "
                "Provision Version Policy integration testing."
            ),
    }


# ============================================================
# SYNTHETIC DOCUMENT VERSION SELECTION
# ============================================================

def build_document_version_selection():
    return {
        "selection_status":
            "selected",

        "failure_reason":
            None,

        "has_conflict":
            False,

        "groups": [
            {
                "group_key":
                    "Kanun:6736",

                "status":
                    "selected",

                "selected_document_ids": [
                    "kanun_6736"
                ],

                "valid_document_ids": [
                    "kanun_6736"
                ],

                "unknown_document_ids":
                    [],

                "invalid_document_ids":
                    [],

                "neutral_document_ids":
                    [],

                "message":
                    (
                        "Synthetic Evaluation V6 "
                        "document version selection."
                    ),
            }
        ],
    }


# ============================================================
# RUN WITH SYNTHETIC PROVISION VERSIONS
#
# Gerçek RAG fonksiyonları:
#
# query parser
# temporal policy
# provision version policy
# provision policy
# deterministic answer
#
# çalışmaya devam eder.
#
#
# Sadece:
#
# document retrieval
# provision repository
#
# kontrollü synthetic veri ile değiştirilir.
# ============================================================

def run_with_synthetic_provisions(
    question,
    provision_candidates,
):
    original_retrieve_candidates = (
        rag_module.retrieve_candidates
    )

    original_resolve_provisions = (
        rag_module.resolve_provisions
    )

    # ========================================================
    # SYNTHETIC DOCUMENT RETRIEVAL
    # ========================================================

    def synthetic_retrieve_candidates(
        search_query,
        metadata,
        temporal_context,
    ):
        temporal_mode = (
            temporal_context.get(
                "mode"
            )
        )

        query_date = (
            temporal_context.get(
                "query_date_string"
            )
        )

        source = (
            build_synthetic_document_source(
                temporal_mode=
                    temporal_mode,

                query_date=
                    query_date,
            )
        )

        return {
            "candidates": [
                source
            ],

            "failure_reason":
                None,

            "retriever_failure_reason":
                None,

            "version_selection":
                build_document_version_selection(),
        }

    # ========================================================
    # SYNTHETIC PROVISION REPOSITORY
    # ========================================================

    def synthetic_resolve_provisions(
        document_id,
        madde=None,
        fikra=None,
        bent=None,
        manifest=None,
    ):
        return {
            "status":
                "resolved",

            "match_type":
                (
                    "parent_fikra"
                    if bent is not None
                    else "exact_fikra"
                ),

            "score":
                (
                    250
                    if bent is not None
                    else 200
                ),

            "provision_id":
                "kanun_6736_m5_f3",

            "candidates":
                copy.deepcopy(
                    provision_candidates
                ),
        }

    try:
        rag_module.retrieve_candidates = (
            synthetic_retrieve_candidates
        )

        rag_module.resolve_provisions = (
            synthetic_resolve_provisions
        )

        result = rag_module.answer_question(
            question=
                question,

            history=
                [],
        )

        return result

    finally:
        rag_module.retrieve_candidates = (
            original_retrieve_candidates
        )

        rag_module.resolve_provisions = (
            original_resolve_provisions
        )


# ============================================================
# COMMON QUESTION
# ============================================================

FORMAL_2020_QUESTION = (
    "6736 sayılı Kanunun "
    "5. maddesinin 3. fıkrası "
    "2020 yılında geçerli miydi?"
)


# ============================================================
# T20
#
# ONE VALID
#
# v1 → invalid
# v2 → valid
#
# EXPECT:
# selected v2
# formal valid
# ============================================================

def test_t20_single_valid_selected():
    candidates = [
        build_synthetic_provision(
            version_id=
                "kanun_6736_m5_f3_v1_old",

            formal_verified=
                True,

            formal_status=
                "historical",

            valid_from=
                "2016-08-19",

            valid_through=
                "2019-12-31",

            repeal_effective_date=
                "2020-01-01",
        ),

        build_synthetic_provision(
            version_id=
                "kanun_6736_m5_f3_v2_current",

            formal_verified=
                True,

            formal_status=
                "active",

            valid_from=
                "2020-01-01",
        ),
    ]

    result = (
        run_with_synthetic_provisions(
            question=
                FORMAL_2020_QUESTION,

            provision_candidates=
                candidates,
        )
    )

    provision = result.get(
        "provision",
        {}
    )

    version_selection = (
        provision.get(
            "version_selection",
            {},
        )
    )

    policy = provision.get(
        "policy",
        {},
    )

    formal = policy.get(
        "formal",
        {},
    )

    assert_equal(
        provision.get(
            "status"
        ),
        "resolved",
        "T20 provision status",
    )

    assert_equal(
        version_selection.get(
            "selection_status"
        ),
        "selected",
        "T20 version selection",
    )

    assert_equal(
        provision.get(
            "provision_version_id"
        ),
        "kanun_6736_m5_f3_v2_current",
        "T20 selected version",
    )

    assert_equal(
        formal.get(
            "result"
        ),
        "valid",
        "T20 formal result",
    )

    assert_contains_any(
        result.get(
            "answer"
        ),
        [
            "valid",
            "formal olarak",
        ],
        "T20 answer",
    )


# ============================================================
# T21
#
# TWO VALID
#
# EXPECT:
# version_conflict
# FAIL CLOSED
# ============================================================

def test_t21_multiple_valid_conflict():
    candidates = [
        build_synthetic_provision(
            version_id=
                "kanun_6736_m5_f3_conflict_v1",

            formal_verified=
                True,

            formal_status=
                "active",

            valid_from=
                "2016-08-19",
        ),

        build_synthetic_provision(
            version_id=
                "kanun_6736_m5_f3_conflict_v2",

            formal_verified=
                True,

            formal_status=
                "active",

            valid_from=
                "2018-01-01",
        ),
    ]

    result = (
        run_with_synthetic_provisions(
            question=
                FORMAL_2020_QUESTION,

            provision_candidates=
                candidates,
        )
    )

    provision = result.get(
        "provision",
        {}
    )

    version_selection = (
        provision.get(
            "version_selection",
            {},
        )
    )

    assert_equal(
        provision.get(
            "status"
        ),
        "version_conflict",
        "T21 provision status",
    )

    assert_equal(
        version_selection.get(
            "selection_status"
        ),
        "version_conflict",
        "T21 version selection",
    )

    assert_equal(
        provision.get(
            "policy"
        ),
        None,
        "T21 policy must not run",
    )

    assert_contains_any(
        result.get(
            "answer"
        ),
        [
            "birden fazla temporal-valid provision sürümü",
            "otomatik provision sürümü seçmedi",
            "yanlış hukuki sürüm",
        ],
        "T21 fail-closed answer",
    )


# ============================================================
# T22
#
# TWO UNKNOWN
#
# EXPECT:
# version_unresolved
# FAIL CLOSED
# ============================================================

def test_t22_multiple_unknown_unresolved():
    candidates = [
        build_synthetic_provision(
            version_id=
                "kanun_6736_m5_f3_unknown_v1",

            formal_verified=
                False,

            formal_status=
                "unknown",
        ),

        build_synthetic_provision(
            version_id=
                "kanun_6736_m5_f3_unknown_v2",

            formal_verified=
                False,

            formal_status=
                "unknown",
        ),
    ]

    result = (
        run_with_synthetic_provisions(
            question=
                FORMAL_2020_QUESTION,

            provision_candidates=
                candidates,
        )
    )

    provision = result.get(
        "provision",
        {}
    )

    version_selection = (
        provision.get(
            "version_selection",
            {},
        )
    )

    assert_equal(
        provision.get(
            "status"
        ),
        "version_unresolved",
        "T22 provision status",
    )

    assert_equal(
        version_selection.get(
            "selection_status"
        ),
        "version_unresolved",
        "T22 version selection",
    )

    assert_equal(
        provision.get(
            "policy"
        ),
        None,
        "T22 policy must not run",
    )

    assert_contains_any(
        result.get(
            "answer"
        ),
        [
            "birden fazla provision sürümü",
            "güvenilir biçimde belirlemeye yeterli değil",
            "tahmin yapmadı",
        ],
        "T22 fail-closed answer",
    )


# ============================================================
# T23
#
# ALL INVALID
#
# EXPECT:
# no_valid_version
# FAIL CLOSED
# ============================================================

def test_t23_no_valid_version():
    candidates = [
        build_synthetic_provision(
            version_id=
                "kanun_6736_m5_f3_old_v1",

            formal_verified=
                True,

            formal_status=
                "historical",

            valid_from=
                "2016-08-19",

            valid_through=
                "2017-12-31",

            repeal_effective_date=
                "2018-01-01",
        ),

        build_synthetic_provision(
            version_id=
                "kanun_6736_m5_f3_old_v2",

            formal_verified=
                True,

            formal_status=
                "historical",

            valid_from=
                "2018-01-01",

            valid_through=
                "2019-12-31",

            repeal_effective_date=
                "2020-01-01",
        ),
    ]

    result = (
        run_with_synthetic_provisions(
            question=
                FORMAL_2020_QUESTION,

            provision_candidates=
                candidates,
        )
    )

    provision = result.get(
        "provision",
        {}
    )

    version_selection = (
        provision.get(
            "version_selection",
            {},
        )
    )

    assert_equal(
        provision.get(
            "status"
        ),
        "no_valid_version",
        "T23 provision status",
    )

    assert_equal(
        version_selection.get(
            "selection_status"
        ),
        "no_valid_version",
        "T23 version selection",
    )

    assert_equal(
        provision.get(
            "policy"
        ),
        None,
        "T23 policy must not run",
    )

    assert_contains_any(
        result.get(
            "answer"
        ),
        [
            "geçerli olduğu doğrulanabilen bir sürüm bulunamadı",
            "yanlış sürümle",
            "fail-closed",
        ],
        "T23 fail-closed answer",
    )


# ============================================================
# T24
#
# SINGLE UNKNOWN
#
# EXPECT:
#
# version_selection = unknown
#
# selected candidate kullanılabilir
#
# AMA:
#
# formal = unknown
#
# VALID DENMEMELİ
# ============================================================

def test_t24_single_unknown_kept_not_valid():
    candidates = [
        build_synthetic_provision(
            version_id=
                "kanun_6736_m5_f3_single_unknown",

            formal_verified=
                False,

            formal_status=
                "unknown",
        )
    ]

    result = (
        run_with_synthetic_provisions(
            question=
                FORMAL_2020_QUESTION,

            provision_candidates=
                candidates,
        )
    )

    provision = result.get(
        "provision",
        {}
    )

    version_selection = (
        provision.get(
            "version_selection",
            {},
        )
    )

    policy = provision.get(
        "policy",
        {},
    )

    formal = policy.get(
        "formal",
        {},
    )

    assert_equal(
        provision.get(
            "status"
        ),
        "resolved",
        "T24 provision status",
    )

    assert_equal(
        version_selection.get(
            "selection_status"
        ),
        "unknown",
        "T24 version status",
    )

    assert_equal(
        provision.get(
            "provision_version_id"
        ),
        "kanun_6736_m5_f3_single_unknown",
        "T24 selected unknown version",
    )

    assert_equal(
        formal.get(
            "result"
        ),
        "unknown",
        "T24 formal result",
    )

    assert_contains_any(
        result.get(
            "answer"
        ),
        [
            "unknown",
            "doğrulanmış değildir",
            "kanıtlamaz",
        ],
        "T24 answer must disclose uncertainty",
    )

    assert_not_contains(
        result.get(
            "answer"
        ),
        [
            "kesin olarak yürürlüktedir",
            "formal olarak `valid`",
            "formal olarak **`valid`**",
        ],
        "T24 must not claim valid",
    )


# ============================================================
# NEW TEST REGISTRY
# ============================================================

NEW_TESTS = [
    (
        "T20",
        (
            "Single valid provision version "
            "selected"
        ),
        test_t20_single_valid_selected,
    ),

    (
        "T21",
        (
            "Multiple valid provision versions "
            "conflict"
        ),
        test_t21_multiple_valid_conflict,
    ),

    (
        "T22",
        (
            "Multiple unknown provision versions "
            "unresolved"
        ),
        test_t22_multiple_unknown_unresolved,
    ),

    (
        "T23",
        "No valid provision version",
        test_t23_no_valid_version,
    ),

    (
        "T24",
        (
            "Single unknown provision version "
            "kept without valid claim"
        ),
        test_t24_single_unknown_kept_not_valid,
    ),
]


# ============================================================
# RUN NEW TESTS
# ============================================================

def run_new_tests():
    print(
        "\n\n======================================"
    )

    print(
        " VERGİ AI - EVALUATION V6"
    )

    print(
        " PROVISION VERSION INTEGRATION"
    )

    print(
        "======================================"
    )

    results = []

    for (
        test_id,
        test_name,
        test_function,
    ) in NEW_TESTS:
        try:
            test_function()

            passed = True
            error = None

        except Exception as exception:
            passed = False
            error = str(
                exception
            )

        results.append(
            {
                "id":
                    test_id,

                "name":
                    test_name,

                "passed":
                    passed,

                "error":
                    error,
            }
        )

        print(
            f"{test_id}:",
            (
                "PASS"
                if passed
                else "FAIL"
            ),
            "-",
            test_name,
        )

        if error:
            print(
                "   ",
                error,
            )

    return results


# ============================================================
# RUN ALL V6
# ============================================================

def run_all_tests():
    print(
        "\n======================================"
    )

    print(
        " VERGİ AI - RAG QUALITY EVALUATION V6"
    )

    print(
        "======================================"
    )

    print(
        "RAG version:",
        getattr(
            rag_module,
            "RAG_VERSION",
            "unknown",
        )
    )

    print(
        "\nAŞAMA 1:"
    )

    print(
        "Evaluation V5 T01-T19 regresyon paketi"
    )

    # ========================================================
    # EXISTING 19 TESTS
    # ========================================================

    old_results = (
        base_evaluation.run_all_tests()
    )

    # ========================================================
    # NEW 5 TESTS
    # ========================================================

    new_results = (
        run_new_tests()
    )

    all_results = (
        old_results
        + new_results
    )

    passed_count = sum(
        1
        for result
        in all_results
        if result.get(
            "passed"
        )
    )

    failed_count = (
        len(
            all_results
        )
        - passed_count
    )

    # ========================================================
    # FINAL V6 SUMMARY
    # ========================================================

    print(
        "\n\n======================================"
    )

    print(
        " EVALUATION V6 - GENEL TEST ÖZETİ"
    )

    print(
        "======================================"
    )

    print(
        "Toplam test:",
        len(
            all_results
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

    for result in all_results:
        print(
            f"{result.get('id')}:",
            (
                "PASS"
                if result.get(
                    "passed"
                )
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

        for result in all_results:
            if result.get(
                "passed"
            ):
                continue

            print(
                f"\n{result.get('id')} - "
                f"{result.get('name')}"
            )

            error = result.get(
                "error"
            )

            if error:
                print(
                    "-",
                    error,
                )

            for detail in result.get(
                "errors",
                [],
            ):
                print(
                    "-",
                    detail,
                )

    print(
        "\n======================================"
    )

    if failed_count:
        raise RuntimeError(
            "Evaluation V6 testlerinden "
            "en az biri başarısız."
        )

    return all_results


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    run_all_tests()