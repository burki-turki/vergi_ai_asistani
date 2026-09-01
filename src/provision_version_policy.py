# ============================================================
# VERGİ AI - PROVISION VERSION POLICY V1
#
# AMAÇ:
#
# Aynı provision_id'ye ait birden fazla hukuki sürüm arasından
# sorgu tarihine uygun provision version'ı güvenli biçimde
# seçmek.
#
#
# KRİTİK PRENSİP:
#
# WRONG VERSION
#     >
# NO VERSION
#
# Yanlış provision sürümü seçmek,
# cevap vermemekten daha tehlikelidir.
#
#
# DOCUMENT VERSION POLICY'DEN AYRI:
#
# document version
#       !=
# provision version
#
#
# ÖRNEK:
#
# Kanun belgesi yürürlükte olabilir.
#
# Ancak:
#
# m.5/3_v1 → 2016-2018
# m.5/3_v2 → 2018-2020
# m.5/3_v3 → 2020-
#
# gibi provision-level farklı sürümler bulunabilir.
#
#
# SEÇİM KURALI:
#
# temporal_mode = neutral
#     → sürüm seçimi yapılmaz
#     → bütün adaylar korunur
#
# temporal_mode = current / historical_date
#
# 1 valid
#     → selected
#
# >1 valid
#     → version_conflict
#
# 0 valid + 1 unknown
#     → unknown
#     → tek unknown aday korunabilir
#
# 0 valid + >1 unknown
#     → version_unresolved
#
# bütün adaylar invalid
#     → no_valid_version
#
#
# ÖNEMLİ:
#
# - version numarası yüksek diye seçim YOK.
# - provision_version_id alfabetik diye seçim YOK.
# - manifest sırası diye seçim YOK.
# - formal verified=False ise sürüm VALID ilan edilmez.
# - tek unknown sürüm kullanılabilir ama UNKNOWN olarak kalır.
#
# ============================================================


try:
    from .provision_policy import (
        evaluate_provision_policy,
    )

except ImportError:
    from provision_policy import (
        evaluate_provision_policy,
    )


# ============================================================
# VERSION
# ============================================================

PROVISION_VERSION_POLICY_VERSION = "1"


# ============================================================
# CONSTANTS
# ============================================================

VALID_TEMPORAL_MODES = {
    "neutral",
    "current",
    "historical_date",
}


# ============================================================
# NORMALIZE
# ============================================================

def normalize(value):
    if value is None:
        return None

    value = str(
        value
    ).strip()

    if not value:
        return None

    return value


# ============================================================
# IDS
# ============================================================

def get_provision_id(
    provision,
):
    return normalize(
        provision.get(
            "provision_id"
        )
    )


def get_provision_version_id(
    provision,
):
    return normalize(
        provision.get(
            "provision_version_id"
        )
    )


# ============================================================
# TEMPORAL FORMAL RESULT
#
# Mevcut Provision Policy'nin formal evaluation sonucunu
# yeniden kullanıyoruz.
#
# Böylece:
#
# Provision Version Policy
#
# kendi başına ikinci bir formal yürürlük motoru oluşturmaz.
#
# Tek truth source:
#
# provision_policy.py
# ============================================================

def evaluate_candidate_temporal_result(
    provision,
    temporal_mode,
    query_date=None,
):
    policy_result = (
        evaluate_provision_policy(
            provision=provision,
            temporal_mode=temporal_mode,
            query_date=query_date,
            question_scope="formal_status",
        )
    )

    formal = policy_result.get(
        "formal",
        {},
    )

    result = normalize(
        formal.get(
            "result"
        )
    )

    if result not in {
        "neutral",
        "valid",
        "invalid",
        "unknown",
    }:
        return "unknown"

    return result


# ============================================================
# CANDIDATE SUMMARY
# ============================================================

def build_candidate_summary(
    provision,
    temporal_result,
):
    return {
        "provision_id":
            get_provision_id(
                provision
            ),

        "provision_version_id":
            get_provision_version_id(
                provision
            ),

        "verification_state":
            provision.get(
                "verification_state"
            ),

        "temporal_result":
            temporal_result,

        "formal_verified":
            provision.get(
                "formal",
                {},
            ).get(
                "verified"
            ),

        "formal_status":
            provision.get(
                "formal",
                {},
            ).get(
                "status"
            ),

        "valid_from":
            provision.get(
                "formal",
                {},
            ).get(
                "valid_from"
            ),

        "valid_through":
            provision.get(
                "formal",
                {},
            ).get(
                "valid_through"
            ),

        "repeal_effective_date":
            provision.get(
                "formal",
                {},
            ).get(
                "repeal_effective_date"
            ),
    }


# ============================================================
# VALIDATE CANDIDATE GROUP
#
# Repository normalde aynı stable provision_id grubunu döndürür.
#
# Buna rağmen Policy kendi sınırında da kontrol eder.
# ============================================================

def validate_candidate_group(
    candidates,
):
    provision_ids = {
        get_provision_id(
            candidate
        )
        for candidate in candidates
        if get_provision_id(
            candidate
        )
        is not None
    }

    if len(
        provision_ids
    ) > 1:
        return {
            "valid":
                False,

            "failure_reason":
                "mixed_provision_candidates",

            "provision_id":
                None,
        }

    provision_id = (
        next(
            iter(
                provision_ids
            )
        )
        if provision_ids
        else None
    )

    return {
        "valid":
            True,

        "failure_reason":
            None,

        "provision_id":
            provision_id,
    }


# ============================================================
# RESULT BUILDER
# ============================================================

def build_result(
    temporal_mode,
    query_date,
    provision_id,
    selection_status,
    failure_reason,
    selected_candidates,
    valid_candidates,
    unknown_candidates,
    invalid_candidates,
    neutral_candidates,
):
    return {
        "policy_version":
            PROVISION_VERSION_POLICY_VERSION,

        "temporal_mode":
            temporal_mode,

        "query_date":
            (
                str(
                    query_date
                )
                if query_date is not None
                else None
            ),

        "provision_id":
            provision_id,

        "selection_status":
            selection_status,

        "failure_reason":
            failure_reason,

        "selected_candidates":
            selected_candidates,

        "selected_provision_version_ids": [
            get_provision_version_id(
                candidate
            )
            for candidate
            in selected_candidates
        ],

        "valid_provision_version_ids": [
            get_provision_version_id(
                candidate
            )
            for candidate
            in valid_candidates
        ],

        "unknown_provision_version_ids": [
            get_provision_version_id(
                candidate
            )
            for candidate
            in unknown_candidates
        ],

        "invalid_provision_version_ids": [
            get_provision_version_id(
                candidate
            )
            for candidate
            in invalid_candidates
        ],

        "neutral_provision_version_ids": [
            get_provision_version_id(
                candidate
            )
            for candidate
            in neutral_candidates
        ],

        "candidate_count":
            (
                len(
                    valid_candidates
                )
                + len(
                    unknown_candidates
                )
                + len(
                    invalid_candidates
                )
                + len(
                    neutral_candidates
                )
            ),
    }


# ============================================================
# SELECT PROVISION VERSION
# ============================================================

def select_provision_versions(
    candidates,
    temporal_mode="neutral",
    query_date=None,
):
    if candidates is None:
        candidates = []

    candidates = [
        candidate
        for candidate
        in candidates
        if isinstance(
            candidate,
            dict
        )
    ]

    # ========================================================
    # TEMPORAL MODE VALIDATION
    # ========================================================

    if temporal_mode not in VALID_TEMPORAL_MODES:
        raise ValueError(
            "Geçersiz temporal_mode: "
            f"{temporal_mode}"
        )

    # ========================================================
    # NO CANDIDATES
    # ========================================================

    if not candidates:
        return build_result(
            temporal_mode=temporal_mode,
            query_date=query_date,
            provision_id=None,

            selection_status=
                "no_candidates",

            failure_reason=
                "no_candidates",

            selected_candidates=[],
            valid_candidates=[],
            unknown_candidates=[],
            invalid_candidates=[],
            neutral_candidates=[],
        )

    # ========================================================
    # GROUP VALIDATION
    # ========================================================

    group_validation = (
        validate_candidate_group(
            candidates
        )
    )

    if not group_validation.get(
        "valid"
    ):
        return build_result(
            temporal_mode=temporal_mode,
            query_date=query_date,
            provision_id=None,

            selection_status=
                "mixed_provision_candidates",

            failure_reason=
                "mixed_provision_candidates",

            selected_candidates=[],
            valid_candidates=[],
            unknown_candidates=[],
            invalid_candidates=[],
            neutral_candidates=[],
        )

    provision_id = (
        group_validation.get(
            "provision_id"
        )
    )

    # ========================================================
    # EVALUATE CANDIDATES
    # ========================================================

    valid_candidates = []
    unknown_candidates = []
    invalid_candidates = []
    neutral_candidates = []

    candidate_summaries = []

    for candidate in candidates:
        temporal_result = (
            evaluate_candidate_temporal_result(
                provision=candidate,
                temporal_mode=temporal_mode,
                query_date=query_date,
            )
        )

        candidate_summaries.append(
            build_candidate_summary(
                provision=candidate,
                temporal_result=
                    temporal_result,
            )
        )

        if temporal_result == "valid":
            valid_candidates.append(
                candidate
            )

        elif temporal_result == "unknown":
            unknown_candidates.append(
                candidate
            )

        elif temporal_result == "invalid":
            invalid_candidates.append(
                candidate
            )

        else:
            neutral_candidates.append(
                candidate
            )

    # ========================================================
    # NEUTRAL MODE
    #
    # Version selection intentionally yapılmaz.
    #
    # Bütün adaylar korunur.
    #
    # RAG entegrasyon katmanı, content query için bunların nasıl
    # kullanılacağını ayrıca belirleyebilir.
    # ========================================================

    if temporal_mode == "neutral":
        result = build_result(
            temporal_mode=temporal_mode,
            query_date=query_date,
            provision_id=provision_id,

            selection_status=
                "neutral",

            failure_reason=
                None,

            selected_candidates=
                list(
                    candidates
                ),

            valid_candidates=
                valid_candidates,

            unknown_candidates=
                unknown_candidates,

            invalid_candidates=
                invalid_candidates,

            neutral_candidates=
                neutral_candidates,
        )

        result[
            "candidate_summaries"
        ] = candidate_summaries

        return result

    # ========================================================
    # EXACTLY ONE VALID
    # ========================================================

    if len(
        valid_candidates
    ) == 1:
        result = build_result(
            temporal_mode=temporal_mode,
            query_date=query_date,
            provision_id=provision_id,

            selection_status=
                "selected",

            failure_reason=
                None,

            selected_candidates=
                valid_candidates,

            valid_candidates=
                valid_candidates,

            unknown_candidates=
                unknown_candidates,

            invalid_candidates=
                invalid_candidates,

            neutral_candidates=
                neutral_candidates,
        )

        result[
            "candidate_summaries"
        ] = candidate_summaries

        return result

    # ========================================================
    # MULTIPLE VALID
    #
    # Metadata conflict.
    #
    # Fail closed.
    # ========================================================

    if len(
        valid_candidates
    ) > 1:
        result = build_result(
            temporal_mode=temporal_mode,
            query_date=query_date,
            provision_id=provision_id,

            selection_status=
                "version_conflict",

            failure_reason=
                "version_conflict",

            selected_candidates=[],

            valid_candidates=
                valid_candidates,

            unknown_candidates=
                unknown_candidates,

            invalid_candidates=
                invalid_candidates,

            neutral_candidates=
                neutral_candidates,
        )

        result[
            "candidate_summaries"
        ] = candidate_summaries

        return result

    # ========================================================
    # NO VALID + EXACTLY ONE UNKNOWN
    #
    # Tek unknown aday tutulabilir.
    #
    # AMA selected/valid denmez.
    # ========================================================

    if len(
        unknown_candidates
    ) == 1:
        result = build_result(
            temporal_mode=temporal_mode,
            query_date=query_date,
            provision_id=provision_id,

            selection_status=
                "unknown",

            failure_reason=
                None,

            selected_candidates=
                unknown_candidates,

            valid_candidates=
                valid_candidates,

            unknown_candidates=
                unknown_candidates,

            invalid_candidates=
                invalid_candidates,

            neutral_candidates=
                neutral_candidates,
        )

        result[
            "candidate_summaries"
        ] = candidate_summaries

        return result

    # ========================================================
    # MULTIPLE UNKNOWN
    #
    # Hangisi doğru version bilinmiyor.
    #
    # Version number kullanarak tahmin YOK.
    # ========================================================

    if len(
        unknown_candidates
    ) > 1:
        result = build_result(
            temporal_mode=temporal_mode,
            query_date=query_date,
            provision_id=provision_id,

            selection_status=
                "version_unresolved",

            failure_reason=
                "version_unresolved",

            selected_candidates=[],

            valid_candidates=
                valid_candidates,

            unknown_candidates=
                unknown_candidates,

            invalid_candidates=
                invalid_candidates,

            neutral_candidates=
                neutral_candidates,
        )

        result[
            "candidate_summaries"
        ] = candidate_summaries

        return result

    # ========================================================
    # ALL INVALID
    # ========================================================

    result = build_result(
        temporal_mode=temporal_mode,
        query_date=query_date,
        provision_id=provision_id,

        selection_status=
            "no_valid_version",

        failure_reason=
            "no_valid_version",

        selected_candidates=[],

        valid_candidates=
            valid_candidates,

        unknown_candidates=
            unknown_candidates,

        invalid_candidates=
            invalid_candidates,

        neutral_candidates=
            neutral_candidates,
    )

    result[
        "candidate_summaries"
    ] = candidate_summaries

    return result


# ============================================================
# SYNTHETIC PROVISION BUILDER
# ============================================================

def build_provision(
    version_id,
    formal_verified,
    formal_status,
    valid_from=None,
    valid_through=None,
    repeal_effective_date=None,
    provision_id="law100_m5_f3",
):
    return {
        "provision_id":
            provision_id,

        "provision_version_id":
            version_id,

        "document_id":
            "law100",

        "enabled":
            True,

        "verification_state":
            (
                "verified"
                if formal_verified
                else "unverified"
            ),

        "locator": {
            "madde": "5",
            "fikra": "3",
            "bent": None,
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
            None,
    }


# ============================================================
# ASSERT
# ============================================================

def assert_equal(
    actual,
    expected,
    message,
):
    if actual != expected:
        raise AssertionError(
            f"{message} | "
            f"beklenen={expected}, "
            f"gerçek={actual}"
        )


# ============================================================
# PV01
#
# Neutral:
#
# version seçme.
# ============================================================

def test_neutral_preserves_candidates():
    candidates = [
        build_provision(
            version_id=
                "law100_m5_f3_v1",

            formal_verified=
                True,

            formal_status=
                "active",

            valid_from=
                "2016-01-01",
        ),

        build_provision(
            version_id=
                "law100_m5_f3_v2",

            formal_verified=
                True,

            formal_status=
                "active",

            valid_from=
                "2020-01-01",
        ),
    ]

    result = select_provision_versions(
        candidates=candidates,
        temporal_mode="neutral",
    )

    assert_equal(
        result[
            "selection_status"
        ],
        "neutral",
        "PV01 status",
    )

    assert_equal(
        len(
            result[
                "selected_candidates"
            ]
        ),
        2,
        "PV01 candidate count",
    )


# ============================================================
# PV02
#
# One valid + one invalid.
# ============================================================

def test_one_valid_selected():
    candidates = [
        build_provision(
            version_id=
                "law100_m5_f3_v1",

            formal_verified=
                True,

            formal_status=
                "historical",

            valid_from=
                "2016-01-01",

            valid_through=
                "2019-12-31",

            repeal_effective_date=
                "2020-01-01",
        ),

        build_provision(
            version_id=
                "law100_m5_f3_v2",

            formal_verified=
                True,

            formal_status=
                "active",

            valid_from=
                "2020-01-01",
        ),
    ]

    result = select_provision_versions(
        candidates=candidates,
        temporal_mode=
            "historical_date",
        query_date=
            "2020-06-01",
    )

    assert_equal(
        result[
            "selection_status"
        ],
        "selected",
        "PV02 status",
    )

    assert_equal(
        result[
            "selected_provision_version_ids"
        ],
        [
            "law100_m5_f3_v2"
        ],
        "PV02 selected version",
    )


# ============================================================
# PV03
#
# Two valid.
#
# Conflict.
# ============================================================

def test_multiple_valid_conflict():
    candidates = [
        build_provision(
            version_id=
                "law100_m5_f3_v1",

            formal_verified=
                True,

            formal_status=
                "active",

            valid_from=
                "2016-01-01",
        ),

        build_provision(
            version_id=
                "law100_m5_f3_v2",

            formal_verified=
                True,

            formal_status=
                "active",

            valid_from=
                "2018-01-01",
        ),
    ]

    result = select_provision_versions(
        candidates=candidates,
        temporal_mode=
            "historical_date",
        query_date=
            "2020-06-01",
    )

    assert_equal(
        result[
            "selection_status"
        ],
        "version_conflict",
        "PV03 status",
    )

    assert_equal(
        len(
            result[
                "selected_candidates"
            ]
        ),
        0,
        "PV03 no selection",
    )


# ============================================================
# PV04
#
# Single unknown.
# ============================================================

def test_single_unknown_kept():
    candidate = build_provision(
        version_id=
            "law100_m5_f3_unknown",

        formal_verified=
            False,

        formal_status=
            "unknown",
    )

    result = select_provision_versions(
        candidates=[
            candidate
        ],

        temporal_mode=
            "historical_date",

        query_date=
            "2020-01-01",
    )

    assert_equal(
        result[
            "selection_status"
        ],
        "unknown",
        "PV04 status",
    )

    assert_equal(
        result[
            "selected_provision_version_ids"
        ],
        [
            "law100_m5_f3_unknown"
        ],
        "PV04 selected unknown",
    )


# ============================================================
# PV05
#
# Multiple unknown.
#
# No guessing.
# ============================================================

def test_multiple_unknown_unresolved():
    candidates = [
        build_provision(
            version_id=
                "law100_m5_f3_unknown_v1",

            formal_verified=
                False,

            formal_status=
                "unknown",
        ),

        build_provision(
            version_id=
                "law100_m5_f3_unknown_v2",

            formal_verified=
                False,

            formal_status=
                "unknown",
        ),
    ]

    result = select_provision_versions(
        candidates=candidates,

        temporal_mode=
            "historical_date",

        query_date=
            "2020-01-01",
    )

    assert_equal(
        result[
            "selection_status"
        ],
        "version_unresolved",
        "PV05 status",
    )

    assert_equal(
        len(
            result[
                "selected_candidates"
            ]
        ),
        0,
        "PV05 no selection",
    )


# ============================================================
# PV06
#
# All invalid.
# ============================================================

def test_no_valid_version():
    candidates = [
        build_provision(
            version_id=
                "law100_m5_f3_v1",

            formal_verified=
                True,

            formal_status=
                "historical",

            valid_from=
                "2016-01-01",

            valid_through=
                "2017-12-31",

            repeal_effective_date=
                "2018-01-01",
        ),

        build_provision(
            version_id=
                "law100_m5_f3_v2",

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

    result = select_provision_versions(
        candidates=candidates,

        temporal_mode=
            "historical_date",

        query_date=
            "2021-01-01",
    )

    assert_equal(
        result[
            "selection_status"
        ],
        "no_valid_version",
        "PV06 status",
    )


# ============================================================
# PV07
#
# Different provision IDs are forbidden.
# ============================================================

def test_mixed_provision_candidates():
    candidates = [
        build_provision(
            version_id=
                "law100_m5_f3_v1",

            formal_verified=
                False,

            formal_status=
                "unknown",

            provision_id=
                "law100_m5_f3",
        ),

        build_provision(
            version_id=
                "law100_m5_f4_v1",

            formal_verified=
                False,

            formal_status=
                "unknown",

            provision_id=
                "law100_m5_f4",
        ),
    ]

    result = select_provision_versions(
        candidates=candidates,

        temporal_mode=
            "historical_date",

        query_date=
            "2020-01-01",
    )

    assert_equal(
        result[
            "selection_status"
        ],
        "mixed_provision_candidates",
        "PV07 status",
    )


# ============================================================
# PV08
#
# REAL 6736 REGRESSION
#
# Current real provision:
#
# formal verified=False
# status unknown
#
# Tek candidate olduğu için:
#
# unknown
#
# olarak korunmalı.
#
# VALID ilan edilmemeli.
# ============================================================

def test_real_6736_single_unknown():
    try:
        from .provision_repository import (
            resolve_provisions,
        )

    except ImportError:
        from provision_repository import (
            resolve_provisions,
        )

    resolution = resolve_provisions(
        document_id=
            "kanun_6736",

        madde=
            "5",

        fikra=
            "3",
    )

    assert_equal(
        resolution.get(
            "status"
        ),
        "resolved",
        "PV08 repository status",
    )

    candidates = resolution.get(
        "candidates",
        [],
    )

    result = select_provision_versions(
        candidates=candidates,

        temporal_mode=
            "historical_date",

        query_date=
            "2020-01-01",
    )

    assert_equal(
        result[
            "selection_status"
        ],
        "unknown",
        "PV08 version status",
    )

    assert_equal(
        result[
            "selected_provision_version_ids"
        ],
        [
            "kanun_6736_m5_f3_v1"
        ],
        "PV08 selected version",
    )


# ============================================================
# RUN TESTS
# ============================================================

def run_tests():
    tests = [
        (
            "PV01",
            "Neutral preserves all versions",
            test_neutral_preserves_candidates,
        ),

        (
            "PV02",
            "Single valid version selected",
            test_one_valid_selected,
        ),

        (
            "PV03",
            "Multiple valid versions conflict",
            test_multiple_valid_conflict,
        ),

        (
            "PV04",
            "Single unknown version kept",
            test_single_unknown_kept,
        ),

        (
            "PV05",
            "Multiple unknown versions unresolved",
            test_multiple_unknown_unresolved,
        ),

        (
            "PV06",
            "No valid provision version",
            test_no_valid_version,
        ),

        (
            "PV07",
            "Mixed provision candidates rejected",
            test_mixed_provision_candidates,
        ),

        (
            "PV08",
            "Real 6736 single unknown regression",
            test_real_6736_single_unknown,
        ),
    ]

    print(
        "\n======================================"
    )

    print(
        " VERGİ AI - PROVISION VERSION"
    )

    print(
        " POLICY V1 TEST"
    )

    print(
        "======================================"
    )

    results = []

    for (
        test_id,
        test_name,
        test_function,
    ) in tests:
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

    passed_count = sum(
        1
        for result
        in results
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
        "\n======================================"
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
        "======================================"
    )

    if failed_count:
        raise RuntimeError(
            "Provision Version Policy "
            "testlerinden en az biri başarısız."
        )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    run_tests()