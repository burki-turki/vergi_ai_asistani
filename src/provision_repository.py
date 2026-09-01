# ============================================================
# VERGİ AI - PROVISION REPOSITORY V1
#
# AMAÇ:
#
# data/provisions.json içindeki provision kayıtlarını
# uygulamanın diğer katmanlarından ayırmak.
#
#
# RAG / Retriever doğrudan JSON dosyasına bağımlı olmayacak.
#
#
# AKIŞ:
#
# provisions.json
#       ↓
# Provision Repository
#       ↓
# document_id + madde + fikra + bent
#       ↓
# uygun provision version adayları
#
#
# KRİTİK PRENSİPLER:
#
# 1. provision_version_id yüksek diye sürüm seçilmez.
#
# 2. Aynı provision_id'nin birden fazla version kaydı
#    olabilir.
#
# 3. Repository temporal/version kararı vermez.
#
# 4. Repository yalnızca doğru adayları bulur.
#
# 5. Bent sorusu için:
#
#       exact bent provision
#
#    yoksa:
#
#       parent fıkra provision
#
#    kullanılabilir.
#
# Örnek:
#
# Query:
#
#   Madde 5
#   Fıkra 3
#   Bent a
#
# Manifest:
#
#   Madde 5
#   Fıkra 3
#   Bent null
#
# Bu parent provision kaydı kullanılabilir.
#
# 6. Ancak birden fazla eşit derecede uygun
#    provision bulunursa tahmin yapılmaz.
#
# ============================================================


import json
import os


# ============================================================
# VERSION
# ============================================================

REPOSITORY_VERSION = "1"


# ============================================================
# PATHS
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(
            __file__
        )
    )
)

DATA_DIR = os.path.join(
    BASE_DIR,
    "data"
)

PROVISIONS_PATH = os.path.join(
    DATA_DIR,
    "provisions.json"
)


# ============================================================
# NORMALIZE
# ============================================================

def normalize(
    value
):

    if value is None:

        return None

    normalized = str(
        value
    ).strip()

    if not normalized:

        return None

    return normalized.lower()


# ============================================================
# LOAD MANIFEST
# ============================================================

def load_provisions_manifest(
    path=None
):

    manifest_path = (
        path
        or PROVISIONS_PATH
    )

    if not os.path.exists(
        manifest_path
    ):

        raise FileNotFoundError(
            "provisions.json bulunamadı:\n"
            f"{manifest_path}"
        )

    with open(
        manifest_path,
        "r",
        encoding="utf-8"
    ) as file:

        manifest = json.load(
            file
        )

    if not isinstance(
        manifest,
        dict
    ):

        raise ValueError(
            "provisions.json kök nesnesi "
            "JSON object olmalıdır."
        )

    provisions = manifest.get(
        "provisions"
    )

    if not isinstance(
        provisions,
        list
    ):

        raise ValueError(
            "provisions.json içinde "
            "'provisions' array bulunamadı."
        )

    return manifest


# ============================================================
# ENABLED PROVISIONS
# ============================================================

def get_enabled_provisions(
    manifest=None
):

    if manifest is None:

        manifest = (
            load_provisions_manifest()
        )

    provisions = manifest.get(
        "provisions",
        []
    )

    return [

        provision

        for provision
        in provisions

        if (
            isinstance(
                provision,
                dict
            )
            and provision.get(
                "enabled"
            )
            is True
        )
    ]


# ============================================================
# LOCATOR
# ============================================================

def get_locator(
    provision
):

    locator = provision.get(
        "locator"
    )

    if not isinstance(
        locator,
        dict
    ):

        return {
            "madde": None,
            "fikra": None,
            "bent": None
        }

    return {

        "madde":
            normalize(
                locator.get(
                    "madde"
                )
            ),

        "fikra":
            normalize(
                locator.get(
                    "fikra"
                )
            ),

        "bent":
            normalize(
                locator.get(
                    "bent"
                )
            )
    }


# ============================================================
# ID
# ============================================================

def get_provision_id(
    provision
):

    return normalize(
        provision.get(
            "provision_id"
        )
    )


def get_provision_version_id(
    provision
):

    return normalize(
        provision.get(
            "provision_version_id"
        )
    )


# ============================================================
# BASE DOCUMENT FILTER
# ============================================================

def filter_by_document(
    provisions,
    document_id
):

    document_id = normalize(
        document_id
    )

    if document_id is None:

        return []

    return [

        provision

        for provision
        in provisions

        if normalize(
            provision.get(
                "document_id"
            )
        ) == document_id
    ]


# ============================================================
# MATCH SCORE
#
# Buradaki score semantic score DEĞİLDİR.
#
# Yalnızca locator specificity score.
#
#
# Öncelik:
#
# exact madde/fıkra/bent     300
#
# parent fıkra provision    250
#
# exact madde/fıkra         200
#
# madde-level provision     100
#
#
# -1 = uygun değil
# ============================================================

def calculate_locator_match_score(
    provision,
    madde=None,
    fikra=None,
    bent=None
):

    query_madde = normalize(
        madde
    )

    query_fikra = normalize(
        fikra
    )

    query_bent = normalize(
        bent
    )

    locator = get_locator(
        provision
    )

    provision_madde = locator[
        "madde"
    ]

    provision_fikra = locator[
        "fikra"
    ]

    provision_bent = locator[
        "bent"
    ]

    # ========================================================
    # MADDE ZORUNLU
    # ========================================================

    if query_madde is None:

        return -1

    if (
        provision_madde
        != query_madde
    ):

        return -1

    # ========================================================
    # QUERY HAS BENT
    # ========================================================

    if query_bent is not None:

        # ----------------------------------------------------
        # Bent varsa query fıkra da beklenir.
        # ----------------------------------------------------

        if query_fikra is None:

            return -1

        # ----------------------------------------------------
        # Provision fıkrası farklıysa uygun değil.
        # ----------------------------------------------------

        if (
            provision_fikra
            != query_fikra
        ):

            return -1

        # ----------------------------------------------------
        # EXACT BENT
        # ----------------------------------------------------

        if (
            provision_bent
            == query_bent
        ):

            return 300

        # ----------------------------------------------------
        # PARENT FIKRA
        #
        # Manifest m5/f3 düzeyinde olabilir.
        # Query m5/f3/a olabilir.
        # ----------------------------------------------------

        if provision_bent is None:

            return 250

        return -1

    # ========================================================
    # QUERY HAS FIKRA BUT NO BENT
    # ========================================================

    if query_fikra is not None:

        if (
            provision_fikra
            != query_fikra
        ):

            return -1

        # ----------------------------------------------------
        # Exact fıkra-level provision
        # ----------------------------------------------------

        if provision_bent is None:

            return 200

        # ----------------------------------------------------
        # Bent-level provision query'den daha dar.
        #
        # Fıkra sorusunda tek bir bendi provision olarak
        # otomatik seçmeyiz.
        # ----------------------------------------------------

        return -1

    # ========================================================
    # QUERY ONLY MADDE
    # ========================================================

    # --------------------------------------------------------
    # Madde-level provision.
    # --------------------------------------------------------

    if (
        provision_fikra is None
        and provision_bent is None
    ):

        return 100

    # --------------------------------------------------------
    # Fıkra-level provision'ı yalnızca madde sorusunda
    # otomatik seçmek güvenli değildir.
    # --------------------------------------------------------

    return -1


# ============================================================
# RESOLVE
#
# RETURN:
#
# {
#   "status": "resolved" | "not_found" | "ambiguous",
#   "match_type": ...,
#   "score": ...,
#   "provision_id": ...,
#   "candidates": [...]
# }
#
#
# Aynı provision_id'nin farklı version kayıtları:
#
# AMBIGUOUS DEĞİLDİR.
#
# Çünkü onlar aynı hukuki provision'ın sürümleridir.
#
# Version seçimini sonraki policy katmanı yapacaktır.
#
#
# Farklı provision_id'ler aynı en yüksek locator score'u
# alıyorsa:
#
# ambiguous
#
# ============================================================

def resolve_provisions(
    document_id,
    madde=None,
    fikra=None,
    bent=None,
    manifest=None
):

    if manifest is None:

        manifest = (
            load_provisions_manifest()
        )

    enabled = get_enabled_provisions(
        manifest
    )

    document_candidates = (
        filter_by_document(
            provisions=
                enabled,

            document_id=
                document_id
        )
    )

    scored = []

    for provision in document_candidates:

        score = (
            calculate_locator_match_score(
                provision=
                    provision,

                madde=
                    madde,

                fikra=
                    fikra,

                bent=
                    bent
            )
        )

        if score < 0:

            continue

        scored.append(
            {
                "score":
                    score,

                "provision":
                    provision
            }
        )

    # ========================================================
    # NOT FOUND
    # ========================================================

    if not scored:

        return {

            "status":
                "not_found",

            "match_type":
                None,

            "score":
                None,

            "provision_id":
                None,

            "candidates":
                []
        }

    # ========================================================
    # BEST LOCATOR SCORE
    # ========================================================

    best_score = max(

        item[
            "score"
        ]

        for item
        in scored
    )

    best_items = [

        item

        for item
        in scored

        if item[
            "score"
        ] == best_score
    ]

    # ========================================================
    # GROUP BY STABLE PROVISION ID
    # ========================================================

    provision_groups = {}

    for item in best_items:

        provision = item[
            "provision"
        ]

        provision_id = (
            get_provision_id(
                provision
            )
        )

        if provision_id is None:

            provision_id = (
                "__missing_provision_id__"
            )

        provision_groups.setdefault(
            provision_id,
            []
        ).append(
            provision
        )

    # ========================================================
    # AMBIGUOUS DIFFERENT PROVISIONS
    # ========================================================

    if len(
        provision_groups
    ) > 1:

        candidates = []

        for group_candidates in (
            provision_groups.values()
        ):

            candidates.extend(
                group_candidates
            )

        return {

            "status":
                "ambiguous",

            "match_type":
                get_match_type(
                    best_score
                ),

            "score":
                best_score,

            "provision_id":
                None,

            "candidates":
                candidates
        }

    # ========================================================
    # RESOLVED STABLE PROVISION
    #
    # Birden fazla version olabilir.
    # Hepsini döndür.
    # ========================================================

    provision_id = next(
        iter(
            provision_groups
        )
    )

    candidates = (
        provision_groups[
            provision_id
        ]
    )

    return {

        "status":
            "resolved",

        "match_type":
            get_match_type(
                best_score
            ),

        "score":
            best_score,

        "provision_id":
            provision_id,

        "candidates":
            candidates
    }


# ============================================================
# MATCH TYPE
# ============================================================

def get_match_type(
    score
):

    mapping = {

        300:
            "exact_bent",

        250:
            "parent_fikra",

        200:
            "exact_fikra",

        100:
            "exact_madde"
    }

    return mapping.get(
        score,
        "unknown"
    )


# ============================================================
# PRINT RESULT
# ============================================================

def print_resolution(
    result
):

    print(
        "\nStatus:",
        result.get(
            "status"
        )
    )

    print(
        "Match type:",
        result.get(
            "match_type"
        )
    )

    print(
        "Score:",
        result.get(
            "score"
        )
    )

    print(
        "Provision ID:",
        result.get(
            "provision_id"
        )
    )

    candidates = result.get(
        "candidates",
        []
    )

    print(
        "Candidate version sayısı:",
        len(
            candidates
        )
    )

    for candidate in candidates:

        print(
            "  -",
            candidate.get(
                "provision_version_id"
            ),
            "|",
            candidate.get(
                "verification_state"
            )
        )


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
# SYNTHETIC MANIFEST
# ============================================================

def build_synthetic_manifest():

    return {

        "schema_version":
            1,

        "provisions": [

            {
                "provision_id":
                    "law100_m5_f3",

                "provision_version_id":
                    "law100_m5_f3_v1",

                "document_id":
                    "law100",

                "enabled":
                    True,

                "verification_state":
                    "verified",

                "locator": {
                    "madde": "5",
                    "fikra": "3",
                    "bent": None
                }
            },

            {
                "provision_id":
                    "law100_m5_f3",

                "provision_version_id":
                    "law100_m5_f3_v2",

                "document_id":
                    "law100",

                "enabled":
                    True,

                "verification_state":
                    "verified",

                "locator": {
                    "madde": "5",
                    "fikra": "3",
                    "bent": None
                }
            },

            {
                "provision_id":
                    "law100_m5_f4",

                "provision_version_id":
                    "law100_m5_f4_v1",

                "document_id":
                    "law100",

                "enabled":
                    True,

                "verification_state":
                    "verified",

                "locator": {
                    "madde": "5",
                    "fikra": "4",
                    "bent": None
                }
            },

            {
                "provision_id":
                    "law100_m6",

                "provision_version_id":
                    "law100_m6_v1",

                "document_id":
                    "law100",

                "enabled":
                    True,

                "verification_state":
                    "verified",

                "locator": {
                    "madde": "6",
                    "fikra": None,
                    "bent": None
                }
            },

            {
                "provision_id":
                    "law100_disabled",

                "provision_version_id":
                    "law100_disabled_v1",

                "document_id":
                    "law100",

                "enabled":
                    False,

                "verification_state":
                    "verified",

                "locator": {
                    "madde": "7",
                    "fikra": None,
                    "bent": None
                }
            }
        ]
    }


# ============================================================
# R01
#
# Gerçek 6736 m5/f3.
# ============================================================

def test_real_6736_fikra():

    result = resolve_provisions(
        document_id=
            "kanun_6736",

        madde=
            "5",

        fikra=
            "3"
    )

    assert_equal(
        result[
            "status"
        ],
        "resolved",
        "Real provision status"
    )

    assert_equal(
        result[
            "match_type"
        ],
        "exact_fikra",
        "Real provision match type"
    )

    assert_equal(
        result[
            "provision_id"
        ],
        "kanun_6736_m5_f3",
        "Real provision id"
    )


# ============================================================
# R02
#
# Bent a sorusu -> parent fıkra provision.
# ============================================================

def test_parent_fikra_fallback():

    result = resolve_provisions(
        document_id=
            "kanun_6736",

        madde=
            "5",

        fikra=
            "3",

        bent=
            "a"
    )

    assert_equal(
        result[
            "status"
        ],
        "resolved",
        "Parent provision status"
    )

    assert_equal(
        result[
            "match_type"
        ],
        "parent_fikra",
        "Parent provision match type"
    )

    assert_equal(
        result[
            "provision_id"
        ],
        "kanun_6736_m5_f3",
        "Parent provision id"
    )


# ============================================================
# R03
#
# Olmayan madde.
# ============================================================

def test_not_found():

    result = resolve_provisions(
        document_id=
            "kanun_6736",

        madde=
            "999"
    )

    assert_equal(
        result[
            "status"
        ],
        "not_found",
        "Not found status"
    )


# ============================================================
# R04
#
# Aynı provision_id'nin iki version'ı
# ambiguity yaratmamalı.
# ============================================================

def test_multiple_versions_same_provision():

    manifest = (
        build_synthetic_manifest()
    )

    result = resolve_provisions(
        document_id=
            "law100",

        madde=
            "5",

        fikra=
            "3",

        manifest=
            manifest
    )

    assert_equal(
        result[
            "status"
        ],
        "resolved",
        "Multiple version status"
    )

    assert_equal(
        len(
            result[
                "candidates"
            ]
        ),
        2,
        "Multiple version candidate count"
    )

    assert_equal(
        result[
            "provision_id"
        ],
        "law100_m5_f3",
        "Stable provision id"
    )


# ============================================================
# R05
#
# Madde sorusundan fıkra provision seçilmez.
#
# Çünkü 5/3 ve 5/4 arasında tahmin yapmak yanlış.
# ============================================================

def test_madde_only_does_not_guess_fikra():

    manifest = (
        build_synthetic_manifest()
    )

    result = resolve_provisions(
        document_id=
            "law100",

        madde=
            "5",

        manifest=
            manifest
    )

    assert_equal(
        result[
            "status"
        ],
        "not_found",
        "Madde-only should not guess fıkra"
    )


# ============================================================
# R06
#
# Disabled kayıt yok sayılmalı.
# ============================================================

def test_disabled_ignored():

    manifest = (
        build_synthetic_manifest()
    )

    result = resolve_provisions(
        document_id=
            "law100",

        madde=
            "7",

        manifest=
            manifest
    )

    assert_equal(
        result[
            "status"
        ],
        "not_found",
        "Disabled provision"
    )


# ============================================================
# R07
#
# Exact madde-level provision.
# ============================================================

def test_exact_madde():

    manifest = (
        build_synthetic_manifest()
    )

    result = resolve_provisions(
        document_id=
            "law100",

        madde=
            "6",

        manifest=
            manifest
    )

    assert_equal(
        result[
            "status"
        ],
        "resolved",
        "Exact madde status"
    )

    assert_equal(
        result[
            "match_type"
        ],
        "exact_madde",
        "Exact madde match type"
    )


# ============================================================
# RUN TESTS
# ============================================================

def run_tests():

    tests = [

        (
            "R01",
            "Real 6736 exact fıkra",
            test_real_6736_fikra
        ),

        (
            "R02",
            "Bent query parent fıkra fallback",
            test_parent_fikra_fallback
        ),

        (
            "R03",
            "Provision not found",
            test_not_found
        ),

        (
            "R04",
            "Multiple versions same provision",
            test_multiple_versions_same_provision
        ),

        (
            "R05",
            "Madde-only does not guess fıkra",
            test_madde_only_does_not_guess_fikra
        ),

        (
            "R06",
            "Disabled provision ignored",
            test_disabled_ignored
        ),

        (
            "R07",
            "Exact madde provision",
            test_exact_madde
        )
    ]

    print(
        "\n======================================"
    )

    print(
        " VERGİ AI - PROVISION REPOSITORY V1"
    )

    print(
        "======================================"
    )

    results = []

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
            "Provision Repository testlerinden "
            "en az biri başarısız."
        )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    run_tests()