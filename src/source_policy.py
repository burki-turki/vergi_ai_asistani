# ============================================================
# VERGİ AI - SOURCE POLICY V1.1
#
# AMAÇ:
#
# Hukuki kaynakların retrieval sırasında kullanılacak
# authority / binding / scope özelliklerini merkezi olarak
# tanımlamak.
#
#
# ÖNEMLİ:
#
# authority_level:
#
# Hukuki normlar hiyerarşisinin matematiksel karşılığı değildir.
#
# Bu değer:
#
# - retrieval scoring
# - source prioritization
# - source presentation
#
# için kullanılan sistem içi bir ağırlıktır.
#
#
# V1.1:
#
# - Bakanlar Kurulu Kararı ayrı belge türü olarak eklendi.
# - Cumhurbaşkanı Kararı ile aynı kategori altında ezilmedi.
# - Public API / mevcut fonksiyonlar korunmuştur.
#
# ============================================================


SOURCE_POLICY_VERSION = "1.1"


# ============================================================
# SOURCE POLICIES
# ============================================================

SOURCE_POLICIES = {

    # ========================================================
    # PRIMARY LEGISLATION
    # ========================================================

    "Kanun": {
        "authority_level": 100,
        "binding_type": "primary_binding",
        "scope": "general",
        "description": (
            "Birincil ve bağlayıcı mevzuat kaynağı."
        )
    },


    # ========================================================
    # EXECUTIVE / REGULATORY DECISIONS
    # ========================================================

    "Bakanlar Kurulu Kararı": {
        "authority_level": 90,
        "binding_type": "binding_regulation",
        "scope": "general",
        "description": (
            "Kanuni yetkiye dayanılarak Bakanlar Kurulu tarafından "
            "alınmış bağlayıcı karar veya düzenleyici kaynaktır."
        )
    },

    "Cumhurbaşkanı Kararı": {
        "authority_level": 90,
        "binding_type": "binding_regulation",
        "scope": "general",
        "description": (
            "Kanuni yetkiye dayalı bağlayıcı Cumhurbaşkanı kararı "
            "veya düzenleyici kaynaktır."
        )
    },


    # ========================================================
    # REGULATIONS
    # ========================================================

    "Yönetmelik": {
        "authority_level": 80,
        "binding_type": "binding_regulation",
        "scope": "general",
        "description": (
            "Kanuna dayanılarak çıkarılan düzenleyici işlem."
        )
    },


    # ========================================================
    # ADMINISTRATIVE REGULATIONS
    # ========================================================

    "Genel Tebliğ": {
        "authority_level": 70,
        "binding_type": "administrative_regulation",
        "scope": "general",
        "description": (
            "İdarenin genel uygulama ve açıklamalarını içeren kaynak."
        )
    },

    "Tebliğ": {
        "authority_level": 70,
        "binding_type": "administrative_regulation",
        "scope": "general",
        "description": (
            "İdarenin genel uygulama ve açıklamalarını içeren kaynak."
        )
    },


    # ========================================================
    # ADMINISTRATIVE GUIDANCE
    # ========================================================

    "Sirküler": {
        "authority_level": 55,
        "binding_type": "administrative_guidance",
        "scope": "general",
        "description": (
            "İdarenin uygulamaya ilişkin açıklama ve görüşlerini içerir."
        )
    },

    "Özelge": {
        "authority_level": 40,
        "binding_type": "case_specific_guidance",
        "scope": "specific",
        "description": (
            "Belirli mükellef veya olaya ilişkin idari görüştür."
        )
    },


    # ========================================================
    # JUDICIAL
    # ========================================================

    "Yargı Kararı": {
        "authority_level": 75,
        "binding_type": "judicial",
        "scope": "case_specific",
        "description": (
            "Uyuşmazlığın hukuki değerlendirilmesini içeren "
            "yargısal kaynak."
        )
    },


    # ========================================================
    # FALLBACK
    # ========================================================

    "Diğer": {
        "authority_level": 20,
        "binding_type": "secondary",
        "scope": "unknown",
        "description": (
            "Diğer veya ikincil nitelikte kaynak."
        )
    }
}


# ============================================================
# KAYNAK POLİTİKASI GETİR
# ============================================================

def get_source_policy(
    belge_turu
):
    return SOURCE_POLICIES.get(
        belge_turu,
        SOURCE_POLICIES[
            "Diğer"
        ]
    )


# ============================================================
# AUTHORITY LEVEL
# ============================================================

def get_authority_level(
    belge_turu
):
    policy = get_source_policy(
        belge_turu
    )

    return policy[
        "authority_level"
    ]


# ============================================================
# BINDING TYPE
# ============================================================

def get_binding_type(
    belge_turu
):
    policy = get_source_policy(
        belge_turu
    )

    return policy[
        "binding_type"
    ]


# ============================================================
# SCOPE
# ============================================================

def get_scope(
    belge_turu
):
    policy = get_source_policy(
        belge_turu
    )

    return policy[
        "scope"
    ]


# ============================================================
# INTERNAL VALIDATION
# ============================================================

def validate_source_policies():
    required_fields = {
        "authority_level",
        "binding_type",
        "scope",
        "description",
    }

    errors = []

    for (
        source_type,
        policy
    ) in SOURCE_POLICIES.items():

        missing = (
            required_fields
            - set(
                policy.keys()
            )
        )

        if missing:
            errors.append(
                f"{source_type}: "
                f"eksik alanlar={sorted(missing)}"
            )

        authority = policy.get(
            "authority_level"
        )

        if not isinstance(
            authority,
            int
        ):
            errors.append(
                f"{source_type}: "
                "authority_level integer olmalı."
            )

        elif not (
            0
            <= authority
            <= 100
        ):
            errors.append(
                f"{source_type}: "
                "authority_level 0-100 arasında olmalı."
            )

        for field in [
            "binding_type",
            "scope",
            "description",
        ]:
            value = policy.get(
                field
            )

            if not isinstance(
                value,
                str
            ) or not value.strip():
                errors.append(
                    f"{source_type}: "
                    f"{field} geçerli string olmalı."
                )

    return errors


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    print(
        "\n======================================"
    )

    print(
        " VERGİ AI - SOURCE POLICY V1.1 TEST"
    )

    print(
        "======================================"
    )

    print(
        "Policy version:",
        SOURCE_POLICY_VERSION
    )

    validation_errors = (
        validate_source_policies()
    )

    if validation_errors:
        print(
            "\nPOLICY VALIDATION: FAIL"
        )

        for error in validation_errors:
            print(
                "-",
                error
            )

        raise RuntimeError(
            "Source Policy validation başarısız."
        )

    print(
        "\nPOLICY VALIDATION: PASS"
    )

    test_sources = [
        "Kanun",
        "Bakanlar Kurulu Kararı",
        "Cumhurbaşkanı Kararı",
        "Yönetmelik",
        "Genel Tebliğ",
        "Sirküler",
        "Özelge",
        "Yargı Kararı",
        "Diğer",
        "Bilinmeyen Kaynak"
    ]

    for source in test_sources:

        policy = get_source_policy(
            source
        )

        print(
            f"\nKaynak: {source}"
        )

        print(
            "Authority:",
            policy[
                "authority_level"
            ]
        )

        print(
            "Binding:",
            policy[
                "binding_type"
            ]
        )

        print(
            "Scope:",
            policy[
                "scope"
            ]
        )

        print(
            "Açıklama:",
            policy[
                "description"
            ]
        )

    # ========================================================
    # REGRESSION ASSERTIONS
    # ========================================================

    assert (
        get_authority_level(
            "Kanun"
        )
        == 100
    )

    assert (
        get_authority_level(
            "Bakanlar Kurulu Kararı"
        )
        == 90
    )

    assert (
        get_binding_type(
            "Bakanlar Kurulu Kararı"
        )
        == "binding_regulation"
    )

    assert (
        get_scope(
            "Bakanlar Kurulu Kararı"
        )
        == "general"
    )

    assert (
        get_authority_level(
            "Cumhurbaşkanı Kararı"
        )
        == 90
    )

    assert (
        get_authority_level(
            "Genel Tebliğ"
        )
        == 70
    )

    assert (
        get_authority_level(
            "Yargı Kararı"
        )
        == 75
    )

    # Bilinmeyen source fallback kontrolü
    assert (
        get_source_policy(
            "Bilinmeyen Kaynak"
        )
        == SOURCE_POLICIES[
            "Diğer"
        ]
    )

    print(
        "\n======================================"
    )

    print(
        " SOURCE POLICY V1.1: PASS"
    )

    print(
        "======================================"
    )