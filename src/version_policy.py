# ============================================================
# VERGİ AI - VERSION POLICY V1.1
#
# Version Selection Policy
#
# V1.1 KRİTİK DÜZELTME:
#
# Retriever runtime candidate yapısı:
#
# {
#     "document_id": "...",
#     "temporal_result": "valid",
#     ...
#     "metadata": {
#         "document_id": "...",
#         ...
#     }
# }
#
# Runtime hesaplanan temporal_result gibi alanlar
# top-level'da bulunur.
#
# V1 sürümünde nested metadata öncelikli okunduğu için:
#
# top-level temporal_result = valid
#
# olmasına rağmen:
#
# nested metadata temporal_result = missing
#
# sonucu UNKNOWN kabul ediliyordu.
#
# V1.1:
#
# nested metadata
#       +
# runtime top-level fields
#       ↓
# MERGED METADATA
#
# Top-level runtime değerleri önceliklidir.
#
#
# KRİTİK PRENSİP:
#
# Yanlış sürüm seçmek,
# hiç sürüm seçmemekten daha kötüdür.
# ============================================================


# ============================================================
# MERGED METADATA
#
# Hem raw ingest document:
#
# {
#   "text": "...",
#   "metadata": {...}
# }
#
# hem Retriever runtime result:
#
# {
#   "text": "...",
#   "metadata": {...},
#   "document_id": "...",
#   "temporal_result": "valid",
#   "final_score": ...
# }
#
# desteklenir.
#
# Öncelik:
#
# nested metadata
#       ↓
# top-level runtime fields override
# ============================================================

def get_metadata(
    item
):

    if not isinstance(
        item,
        dict
    ):

        return {}

    merged = {}

    nested = item.get(
        "metadata"
    )

    if isinstance(
        nested,
        dict
    ):

        merged.update(
            nested
        )

    # --------------------------------------------------------
    # Runtime / flat alanlar nested metadata üzerine yazılır.
    #
    # text ve page_content metadata değildir.
    # --------------------------------------------------------

    for key, value in item.items():

        if key in {
            "metadata",
            "text",
            "page_content"
        }:

            continue

        merged[
            key
        ] = value

    return merged


# ============================================================
# VALUE
# ============================================================

def get_value(
    item,
    key,
    default=None
):

    metadata = get_metadata(
        item
    )

    return metadata.get(
        key,
        default
    )


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_string(
    value
):

    if value is None:

        return None

    return str(
        value
    ).strip()


def normalize_lower(
    value
):

    normalized = normalize_string(
        value
    )

    if normalized is None:

        return None

    return normalized.lower()


# ============================================================
# DOCUMENT ID
# ============================================================

def get_document_id(
    item
):

    return normalize_string(
        get_value(
            item,
            "document_id"
        )
    )


# ============================================================
# VERSION
# ============================================================

def get_version(
    item
):

    return normalize_string(
        get_value(
            item,
            "version"
        )
    )


# ============================================================
# TEMPORAL RESULT
# ============================================================

def get_temporal_result(
    item
):

    result = normalize_lower(
        get_value(
            item,
            "temporal_result"
        )
    )

    if result in {
        "valid",
        "invalid",
        "unknown",
        "neutral"
    }:

        return result

    return "unknown"


# ============================================================
# VERSION GROUP KEY
#
# Aynı hukuki enstrümanın sürümlerini
# aynı grupta toplar.
#
# Örnek:
#
# Kanun:6736
#
# İleride explicit instrument_id alanı eklenebilir.
# ============================================================

def get_version_group_key(
    item
):

    belge_turu = normalize_string(
        get_value(
            item,
            "belge_turu"
        )
    )

    kanun_no = normalize_string(
        get_value(
            item,
            "kanun_no"
        )
    )

    document_number = normalize_string(
        get_value(
            item,
            "document_number"
        )
    )

    document_id = get_document_id(
        item
    )

    if kanun_no:

        return (
            "Kanun:"
            f"{kanun_no}"
        )

    if document_number:

        return (
            f"{belge_turu or 'Belge'}:"
            f"{document_number}"
        )

    if document_id:

        return (
            "document:"
            f"{document_id}"
        )

    return "document:unknown"


# ============================================================
# UNIQUE DOCUMENT VERSIONS
#
# Aynı document_id için birden fazla chunk bulunabilir.
#
# Version selection chunk bazında değil,
# belge sürümü bazında yapılır.
# ============================================================

def get_unique_document_versions(
    candidates
):

    documents = {}

    anonymous_counter = 0

    for candidate in candidates:

        document_id = get_document_id(
            candidate
        )

        if document_id is None:

            anonymous_counter += 1

            document_id = (
                "__anonymous_"
                f"{anonymous_counter}"
            )

        if document_id not in documents:

            documents[
                document_id
            ] = candidate

    return documents


# ============================================================
# GROUP DOCUMENT VERSIONS
# ============================================================

def group_document_versions(
    candidates
):

    unique_documents = (
        get_unique_document_versions(
            candidates
        )
    )

    groups = {}

    for document_id, document in (
        unique_documents.items()
    ):

        group_key = (
            get_version_group_key(
                document
            )
        )

        if group_key not in groups:

            groups[
                group_key
            ] = []

        groups[
            group_key
        ].append(
            {
                "document_id":
                    document_id,

                "version":
                    get_version(
                        document
                    ),

                "temporal_result":
                    get_temporal_result(
                        document
                    ),

                "previous_version":
                    normalize_string(
                        get_value(
                            document,
                            "previous_version"
                        )
                    ),

                "next_version":
                    normalize_string(
                        get_value(
                            document,
                            "next_version"
                        )
                    ),

                "candidate":
                    document
            }
        )

    return groups


# ============================================================
# DOCUMENT ID FILTER
# ============================================================

def filter_candidates_by_document_ids(
    candidates,
    document_ids
):

    allowed = set(
        document_ids
    )

    return [

        candidate

        for candidate
        in candidates

        if get_document_id(
            candidate
        ) in allowed

    ]


# ============================================================
# GROUP RESULT HELPER
# ============================================================

def build_group_result(
    group_key,
    status,
    versions,
    selected_document_ids,
    message
):

    valid_document_ids = [

        version[
            "document_id"
        ]

        for version in versions

        if version[
            "temporal_result"
        ] == "valid"
    ]

    unknown_document_ids = [

        version[
            "document_id"
        ]

        for version in versions

        if version[
            "temporal_result"
        ] == "unknown"
    ]

    invalid_document_ids = [

        version[
            "document_id"
        ]

        for version in versions

        if version[
            "temporal_result"
        ] == "invalid"
    ]

    neutral_document_ids = [

        version[
            "document_id"
        ]

        for version in versions

        if version[
            "temporal_result"
        ] == "neutral"
    ]

    return {

        "group_key":
            group_key,

        "status":
            status,

        "selected_document_ids":
            selected_document_ids,

        "valid_document_ids":
            valid_document_ids,

        "unknown_document_ids":
            unknown_document_ids,

        "invalid_document_ids":
            invalid_document_ids,

        "neutral_document_ids":
            neutral_document_ids,

        "message":
            message
    }


# ============================================================
# SINGLE GROUP SELECTION
# ============================================================

def select_group_version(
    group_key,
    versions,
    temporal_mode
):

    valid_versions = [

        version

        for version in versions

        if version[
            "temporal_result"
        ] == "valid"
    ]

    unknown_versions = [

        version

        for version in versions

        if version[
            "temporal_result"
        ] == "unknown"
    ]

    # ========================================================
    # NEUTRAL
    #
    # Temporal version selection uygulanmaz.
    # ========================================================

    if temporal_mode == "neutral":

        return build_group_result(
            group_key=
                group_key,

            status=
                "neutral",

            versions=
                versions,

            selected_document_ids=[

                version[
                    "document_id"
                ]

                for version in versions
            ],

            message=
                (
                    "Neutral sorgu: temporal "
                    "version selection uygulanmadı."
                )
        )

    # ========================================================
    # ONE VALID
    # ========================================================

    if len(
        valid_versions
    ) == 1:

        selected = valid_versions[
            0
        ]

        return build_group_result(
            group_key=
                group_key,

            status=
                "selected",

            versions=
                versions,

            selected_document_ids=[
                selected[
                    "document_id"
                ]
            ],

            message=
                (
                    "Tek temporal-valid sürüm "
                    "bulundu ve seçildi."
                )
        )

    # ========================================================
    # MULTIPLE VALID
    #
    # FAIL CLOSED
    # ========================================================

    if len(
        valid_versions
    ) > 1:

        return build_group_result(
            group_key=
                group_key,

            status=
                "version_conflict",

            versions=
                versions,

            selected_document_ids=
                [],

            message=
                (
                    "Birden fazla temporal-valid sürüm "
                    "bulundu. Otomatik sürüm seçimi yapılmadı."
                )
        )

    # ========================================================
    # ONE UNKNOWN
    # ========================================================

    if len(
        unknown_versions
    ) == 1:

        selected = unknown_versions[
            0
        ]

        return build_group_result(
            group_key=
                group_key,

            status=
                "unknown",

            versions=
                versions,

            selected_document_ids=[
                selected[
                    "document_id"
                ]
            ],

            message=
                (
                    "Tek unknown sürüm bulundu. "
                    "İçerik kullanılabilir ancak temporal "
                    "geçerlilik kesin kabul edilemez."
                )
        )

    # ========================================================
    # MULTIPLE UNKNOWN
    #
    # FAIL CLOSED
    # ========================================================

    if len(
        unknown_versions
    ) > 1:

        return build_group_result(
            group_key=
                group_key,

            status=
                "version_unresolved",

            versions=
                versions,

            selected_document_ids=
                [],

            message=
                (
                    "Birden fazla temporal-unknown sürüm "
                    "bulundu. Doğru sürüm doğrulanamadığı "
                    "için otomatik seçim yapılmadı."
                )
        )

    # ========================================================
    # NO VALID / UNKNOWN
    # ========================================================

    return build_group_result(
        group_key=
            group_key,

        status=
            "no_valid_version",

        versions=
            versions,

        selected_document_ids=
            [],

        message=
            (
                "Temporal olarak kullanılabilir "
                "bir sürüm bulunamadı."
            )
    )


# ============================================================
# OVERALL STATUS
# ============================================================

def calculate_overall_status(
    group_results
):

    if not group_results:

        return "no_candidate"

    statuses = {

        result[
            "status"
        ]

        for result in group_results
    }

    if statuses == {
        "neutral"
    }:

        return "neutral"

    if "version_conflict" in statuses:

        return "version_conflict"

    if "version_unresolved" in statuses:

        return "version_unresolved"

    if statuses == {
        "no_valid_version"
    }:

        return "no_valid_version"

    if statuses <= {
        "selected"
    }:

        return "selected"

    if statuses <= {
        "unknown"
    }:

        return "unknown"

    if statuses <= {
        "selected",
        "unknown"
    }:

        return "selected_with_unknown"

    return "mixed"


# ============================================================
# FAILURE REASON
# ============================================================

def calculate_failure_reason(
    overall_status
):

    mapping = {

        "version_conflict":
            "version_conflict",

        "version_unresolved":
            "version_unresolved",

        "no_valid_version":
            "no_valid_version",

        "no_candidate":
            "no_candidate"
    }

    return mapping.get(
        overall_status
    )


# ============================================================
# MAIN VERSION SELECTION
# ============================================================

def select_versions(
    candidates,
    temporal_mode="neutral"
):

    if candidates is None:

        candidates = []

    temporal_mode = (
        normalize_lower(
            temporal_mode
        )
        or "neutral"
    )

    if temporal_mode not in {
        "neutral",
        "current",
        "historical_date"
    }:

        raise ValueError(
            "Geçersiz temporal_mode: "
            f"{temporal_mode}"
        )

    # ========================================================
    # NO CANDIDATE
    # ========================================================

    if not candidates:

        return {

            "candidates":
                [],

            "temporal_mode":
                temporal_mode,

            "selection_status":
                "no_candidate",

            "failure_reason":
                "no_candidate",

            "has_conflict":
                False,

            "groups":
                []
        }

    # ========================================================
    # GROUP
    # ========================================================

    groups = group_document_versions(
        candidates
    )

    group_results = []

    selected_document_ids = []

    for group_key, versions in (
        groups.items()
    ):

        group_result = (
            select_group_version(
                group_key=
                    group_key,

                versions=
                    versions,

                temporal_mode=
                    temporal_mode
            )
        )

        group_results.append(
            group_result
        )

        selected_document_ids.extend(
            group_result.get(
                "selected_document_ids",
                []
            )
        )

    # ========================================================
    # OVERALL
    # ========================================================

    overall_status = (
        calculate_overall_status(
            group_results
        )
    )

    failure_reason = (
        calculate_failure_reason(
            overall_status
        )
    )

    has_conflict = (
        overall_status
        in {
            "version_conflict",
            "version_unresolved"
        }
    )

    # ========================================================
    # FILTER
    # ========================================================

    filtered_candidates = (
        filter_candidates_by_document_ids(
            candidates=
                candidates,

            document_ids=
                selected_document_ids
        )
    )

    return {

        "candidates":
            filtered_candidates,

        "temporal_mode":
            temporal_mode,

        "selection_status":
            overall_status,

        "failure_reason":
            failure_reason,

        "has_conflict":
            has_conflict,

        "groups":
            group_results
    }


# ============================================================
# DEBUG PRINT
# ============================================================

def print_version_selection(
    result
):

    print(
        "\n======================================"
    )

    print(
        " VERSION SELECTION"
    )

    print(
        "======================================"
    )

    print(
        "Temporal mode:",
        result.get(
            "temporal_mode"
        )
    )

    print(
        "Selection status:",
        result.get(
            "selection_status"
        )
    )

    print(
        "Failure reason:",
        result.get(
            "failure_reason"
        )
    )

    print(
        "Conflict:",
        result.get(
            "has_conflict"
        )
    )

    print(
        "Selected chunks:",
        len(
            result.get(
                "candidates",
                []
            )
        )
    )

    for group in result.get(
        "groups",
        []
    ):

        print(
            "\n--------------------------------------"
        )

        print(
            "Group:",
            group.get(
                "group_key"
            )
        )

        print(
            "Status:",
            group.get(
                "status"
            )
        )

        print(
            "Selected:",
            group.get(
                "selected_document_ids"
            )
        )

        print(
            "Valid:",
            group.get(
                "valid_document_ids"
            )
        )

        print(
            "Unknown:",
            group.get(
                "unknown_document_ids"
            )
        )

        print(
            "Invalid:",
            group.get(
                "invalid_document_ids"
            )
        )

        print(
            "Message:",
            group.get(
                "message"
            )
        )


# ============================================================
# SYNTHETIC TEST CANDIDATE
# ============================================================

def make_test_candidate(
    document_id,
    version,
    temporal_result,
    chunk_id
):

    return {

        "document_id":
            document_id,

        "belge_turu":
            "Kanun",

        "kanun_no":
            "TEST1000",

        "document_number":
            "TEST1000",

        "version":
            version,

        "temporal_result":
            temporal_result,

        "chunk_id":
            chunk_id,

        "text":
            (
                "Bu içerik yalnızca sentetik "
                "version-selection test verisidir."
            )
    }


# ============================================================
# RUNTIME-STYLE TEST CANDIDATE
#
# Retriever build_result() yapısını taklit eder.
#
# Nested metadata'da temporal_result YOK.
# Runtime top-level'da temporal_result VAR.
#
# V1 bug'ını doğrudan test eder.
# ============================================================

def make_runtime_test_candidate(
    document_id,
    version,
    temporal_result,
    chunk_id
):

    return {

        "text":
            "Runtime candidate sentetik test.",

        "metadata": {

            "document_id":
                document_id,

            "belge_turu":
                "Kanun",

            "kanun_no":
                "TEST2000",

            "document_number":
                "TEST2000",

            "version":
                version
        },

        "document_id":
            document_id,

        "belge_turu":
            "Kanun",

        "kanun_no":
            "TEST2000",

        "document_number":
            "TEST2000",

        "version":
            version,

        # ----------------------------------------------------
        # KRİTİK:
        # Bu nested metadata'da yok.
        # ----------------------------------------------------

        "temporal_result":
            temporal_result,

        "temporal_score":
            (
                1.0
                if temporal_result
                == "valid"
                else 0.5
            ),

        "chunk_id":
            chunk_id,

        "final_score":
            0.8
    }


# ============================================================
# ASSERT
# ============================================================

def assert_equal(
    actual,
    expected,
    message
):

    if actual != expected:

        raise AssertionError(
            f"{message} | "
            f"beklenen={expected}, "
            f"gerçek={actual}"
        )


# ============================================================
# V01
# ============================================================

def test_neutral():

    candidates = [

        make_test_candidate(
            "test_v1",
            "1",
            "neutral",
            "v1_c1"
        ),

        make_test_candidate(
            "test_v2",
            "2",
            "neutral",
            "v2_c1"
        )
    ]

    result = select_versions(
        candidates,
        temporal_mode="neutral"
    )

    assert_equal(
        result[
            "selection_status"
        ],
        "neutral",
        "Neutral status"
    )

    assert_equal(
        len(
            result[
                "candidates"
            ]
        ),
        2,
        "Neutral candidate count"
    )


# ============================================================
# V02
# ============================================================

def test_single_valid():

    candidates = [

        make_test_candidate(
            "test_v1",
            "1",
            "valid",
            "v1_c1"
        ),

        make_test_candidate(
            "test_v1",
            "1",
            "valid",
            "v1_c2"
        ),

        make_test_candidate(
            "test_v2",
            "2",
            "invalid",
            "v2_c1"
        )
    ]

    result = select_versions(
        candidates,
        temporal_mode=
            "historical_date"
    )

    assert_equal(
        result[
            "selection_status"
        ],
        "selected",
        "Single valid status"
    )

    selected_ids = {

        get_document_id(
            candidate
        )

        for candidate
        in result[
            "candidates"
        ]
    }

    assert_equal(
        selected_ids,
        {
            "test_v1"
        },
        "Selected document"
    )

    assert_equal(
        len(
            result[
                "candidates"
            ]
        ),
        2,
        "Selected chunk count"
    )


# ============================================================
# V03
# ============================================================

def test_multiple_valid_conflict():

    candidates = [

        make_test_candidate(
            "test_v1",
            "1",
            "valid",
            "v1_c1"
        ),

        make_test_candidate(
            "test_v2",
            "2",
            "valid",
            "v2_c1"
        )
    ]

    result = select_versions(
        candidates,
        temporal_mode=
            "historical_date"
    )

    assert_equal(
        result[
            "selection_status"
        ],
        "version_conflict",
        "Conflict status"
    )

    assert_equal(
        result[
            "failure_reason"
        ],
        "version_conflict",
        "Conflict failure reason"
    )

    assert_equal(
        len(
            result[
                "candidates"
            ]
        ),
        0,
        "Conflict candidate count"
    )


# ============================================================
# V04
# ============================================================

def test_single_unknown():

    candidates = [

        make_test_candidate(
            "test_v1",
            "1",
            "unknown",
            "v1_c1"
        ),

        make_test_candidate(
            "test_v1",
            "1",
            "unknown",
            "v1_c2"
        )
    ]

    result = select_versions(
        candidates,
        temporal_mode=
            "historical_date"
    )

    assert_equal(
        result[
            "selection_status"
        ],
        "unknown",
        "Unknown status"
    )

    assert_equal(
        len(
            result[
                "candidates"
            ]
        ),
        2,
        "Unknown chunk count"
    )


# ============================================================
# V05
# ============================================================

def test_multiple_unknown_unresolved():

    candidates = [

        make_test_candidate(
            "test_v1",
            "1",
            "unknown",
            "v1_c1"
        ),

        make_test_candidate(
            "test_v2",
            "2",
            "unknown",
            "v2_c1"
        )
    ]

    result = select_versions(
        candidates,
        temporal_mode=
            "historical_date"
    )

    assert_equal(
        result[
            "selection_status"
        ],
        "version_unresolved",
        "Unresolved status"
    )

    assert_equal(
        result[
            "failure_reason"
        ],
        "version_unresolved",
        "Unresolved failure reason"
    )

    assert_equal(
        len(
            result[
                "candidates"
            ]
        ),
        0,
        "Unresolved candidate count"
    )


# ============================================================
# V06
# ============================================================

def test_no_valid_version():

    candidates = [

        make_test_candidate(
            "test_v1",
            "1",
            "invalid",
            "v1_c1"
        ),

        make_test_candidate(
            "test_v2",
            "2",
            "invalid",
            "v2_c1"
        )
    ]

    result = select_versions(
        candidates,
        temporal_mode=
            "historical_date"
    )

    assert_equal(
        result[
            "selection_status"
        ],
        "no_valid_version",
        "No-valid status"
    )

    assert_equal(
        result[
            "failure_reason"
        ],
        "no_valid_version",
        "No-valid failure reason"
    )

    assert_equal(
        len(
            result[
                "candidates"
            ]
        ),
        0,
        "No-valid candidate count"
    )


# ============================================================
# V07
#
# Retriever runtime structure regression test.
#
# Bu test V1.1'in kritik testidir.
# ============================================================

def test_runtime_top_level_temporal_override():

    candidates = [

        make_runtime_test_candidate(
            document_id=
                "runtime_v1",

            version=
                "1",

            temporal_result=
                "valid",

            chunk_id=
                "runtime_c1"
        ),

        make_runtime_test_candidate(
            document_id=
                "runtime_v1",

            version=
                "1",

            temporal_result=
                "valid",

            chunk_id=
                "runtime_c2"
        )
    ]

    # --------------------------------------------------------
    # Önce doğrudan temporal_result okumasını test et.
    # --------------------------------------------------------

    actual_temporal = (
        get_temporal_result(
            candidates[
                0
            ]
        )
    )

    assert_equal(
        actual_temporal,
        "valid",
        "Runtime top-level temporal_result"
    )

    # --------------------------------------------------------
    # Sonra gerçek version selection.
    # --------------------------------------------------------

    result = select_versions(
        candidates,
        temporal_mode=
            "current"
    )

    assert_equal(
        result[
            "selection_status"
        ],
        "selected",
        "Runtime version selection status"
    )

    assert_equal(
        result[
            "groups"
        ][
            0
        ][
            "valid_document_ids"
        ],
        [
            "runtime_v1"
        ],
        "Runtime valid document"
    )

    assert_equal(
        result[
            "groups"
        ][
            0
        ][
            "unknown_document_ids"
        ],
        [],
        "Runtime unknown list"
    )

    assert_equal(
        len(
            result[
                "candidates"
            ]
        ),
        2,
        "Runtime selected chunks"
    )


# ============================================================
# RUN TESTS
# ============================================================

def run_tests():

    tests = [

        (
            "V01",
            "Neutral version selection",
            test_neutral
        ),

        (
            "V02",
            "Single valid version",
            test_single_valid
        ),

        (
            "V03",
            "Multiple valid conflict",
            test_multiple_valid_conflict
        ),

        (
            "V04",
            "Single unknown version",
            test_single_unknown
        ),

        (
            "V05",
            "Multiple unknown unresolved",
            test_multiple_unknown_unresolved
        ),

        (
            "V06",
            "No valid version",
            test_no_valid_version
        ),

        (
            "V07",
            "Retriever runtime temporal override",
            test_runtime_top_level_temporal_override
        )
    ]

    results = []

    print(
        "\n======================================"
    )

    print(
        " VERGİ AI - VERSION POLICY V1.1 TEST"
    )

    print(
        "======================================"
    )

    for (
        test_id,
        test_name,
        test_function
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
                    error
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
            test_name
        )

        if error:

            print(
                "   ",
                error
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
            "Version Policy testlerinden "
            "en az biri başarısız."
        )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    run_tests()