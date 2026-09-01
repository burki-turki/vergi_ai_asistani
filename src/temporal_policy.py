# ============================================================
# VERGİ AI - TEMPORAL POLICY V2
#
# Amaç:
# - Normal hukuki soruları gereksiz yere zaman filtresine sokmamak
# - Açık "güncel" soruları current modunda değerlendirmek
# - Açık tarih içeren soruları historical_date modunda değerlendirmek
# - Geçerliliği bilinmeyen belgeyi yanlış biçimde geçerli/geçersiz
#   ilan etmemek
# ============================================================

import re

from datetime import (
    date,
    datetime
)


# ============================================================
# STATUS GRUPLARI
# ============================================================

CURRENT_STATUSES = {
    "active",
    "amended",
    "partially_repealed"
}


HISTORICAL_STATUSES = {
    "historical",
    "repealed"
}


# ============================================================
# TEMPORAL SONUÇLAR
# ============================================================

TEMPORAL_VALID = "valid"

TEMPORAL_INVALID = "invalid"

TEMPORAL_UNKNOWN = "unknown"

TEMPORAL_NEUTRAL = "neutral"


# ============================================================
# TARİH NORMALİZASYONU
# ============================================================

def normalize_date_value(
    value
):

    if value is None:

        return None


    if isinstance(
        value,
        datetime
    ):

        return value.date()


    if isinstance(
        value,
        date
    ):

        return value


    value = str(
        value
    ).strip()


    if not value:

        return None


    # ========================================================
    # YYYY-MM-DD
    # ========================================================

    try:

        return date.fromisoformat(
            value
        )

    except ValueError:

        pass


    # ========================================================
    # DD.MM.YYYY
    # ========================================================

    try:

        return datetime.strptime(
            value,
            "%d.%m.%Y"
        ).date()

    except ValueError:

        pass


    # ========================================================
    # DD/MM/YYYY
    # ========================================================

    try:

        return datetime.strptime(
            value,
            "%d/%m/%Y"
        ).date()

    except ValueError:

        pass


    raise ValueError(
        f"Geçersiz tarih formatı: {value}"
    )


# ============================================================
# SORUDAN AÇIK TARİH ÇIKAR
# ============================================================

def extract_query_date(
    query
):

    if not query:

        return None


    text = str(
        query
    )


    # ========================================================
    # 1. YYYY-MM-DD
    # ========================================================

    match = re.search(
        r"\b(\d{4}-\d{2}-\d{2})\b",
        text
    )


    if match:

        try:

            return date.fromisoformat(
                match.group(1)
            )

        except ValueError:

            pass


    # ========================================================
    # 2. DD.MM.YYYY
    # ========================================================

    match = re.search(
        r"\b(\d{1,2}\.\d{1,2}\.\d{4})\b",
        text
    )


    if match:

        try:

            return datetime.strptime(
                match.group(1),
                "%d.%m.%Y"
            ).date()

        except ValueError:

            pass


    # ========================================================
    # 3. DD/MM/YYYY
    # ========================================================

    match = re.search(
        r"\b(\d{1,2}/\d{1,2}/\d{4})\b",
        text
    )


    if match:

        try:

            return datetime.strptime(
                match.group(1),
                "%d/%m/%Y"
            ).date()

        except ValueError:

            pass


    # ========================================================
    # 4. SADECE YIL
    #
    # V2'de hâlâ temsil tarihi olarak 1 Ocak kullanıyoruz.
    # Daha sonra "year interval" desteği ekleyeceğiz.
    # ========================================================

    year_patterns = [

        r"\b(19\d{2}|20\d{2})\s+yılında\b",

        r"\b(19\d{2}|20\d{2})['’]?(?:de|da|te|ta)\b",

        r"\b(19\d{2}|20\d{2})\s+tarihinde\b",

        r"\b(19\d{2}|20\d{2})\s+yılı\b"
    ]


    for pattern in year_patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )


        if match:

            return date(
                int(
                    match.group(1)
                ),
                1,
                1
            )


    return None


# ============================================================
# GÜNCEL ZAMAN NİYETİ VAR MI?
# ============================================================

def has_current_intent(
    query
):

    if not query:

        return False


    text = str(
        query
    ).lower()


    patterns = [

        r"\bbugün\b",

        r"\bşu anda\b",

        r"\bhalen\b",

        r"\bhâlen\b",

        r"\bgüncel\b",

        r"\byürürlükte\b",

        r"\byürürlükteki\b",

        r"\bşimdiki\b",

        r"\bmevcut düzenleme\b",

        r"\bmevcut hüküm\b",

        r"\bhalihazırda\b",

        r"\bhâlihazırda\b"
    ]


    return any(

        re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        for pattern
        in patterns

    )


# ============================================================
# TEMPORAL MODE
# ============================================================

def get_temporal_mode(
    query
):

    query_date = extract_query_date(
        query
    )


    # ========================================================
    # AÇIK TARİH VAR
    # ========================================================

    if query_date is not None:

        return {
            "mode":
                "historical_date",

            "query_date":
                query_date
        }


    # ========================================================
    # AÇIK GÜNCEL NİYET VAR
    # ========================================================

    if has_current_intent(
        query
    ):

        return {
            "mode":
                "current",

            "query_date":
                None
        }


    # ========================================================
    # NORMAL HUKUKİ SORU
    # ========================================================

    return {
        "mode":
            "neutral",

        "query_date":
            None
    }


# ============================================================
# BELGE GEÇERLİLİK TARİHLERİ
# ============================================================

def get_validity_dates(
    document
):

    start = normalize_date_value(
        document.get(
            "gecerlilik_baslangici"
        )
    )


    end = normalize_date_value(
        document.get(
            "gecerlilik_sonu"
        )
    )


    repeal = normalize_date_value(
        document.get(
            "mulga_tarihi"
        )
    )


    effective = normalize_date_value(
        document.get(
            "yururluk_tarihi"
        )
    )


    # ========================================================
    # Geçerlilik başlangıcı bilinmiyorsa
    # yürürlük tarihi fallback olabilir.
    # ========================================================

    if start is None:

        start = effective


    # ========================================================
    # Geçerlilik sonu yoksa mülga tarihi fallback olabilir.
    # ========================================================

    if end is None:

        end = repeal


    return (
        start,
        end
    )


# ============================================================
# TARİH BİLGİSİ VAR MI?
# ============================================================

def has_temporal_metadata(
    document
):

    fields = [

        "yururluk_tarihi",

        "gecerlilik_baslangici",

        "gecerlilik_sonu",

        "mulga_tarihi"
    ]


    return any(

        document.get(
            field
        )
        is not None

        for field
        in fields

    )


# ============================================================
# BELGE BELİRLİ TARİHTE GEÇERLİ Mİ?
#
# Üç durum:
# valid
# invalid
# unknown
# ============================================================

def evaluate_on_date(
    document,
    query_date
):

    query_date = normalize_date_value(
        query_date
    )


    if query_date is None:

        return TEMPORAL_UNKNOWN


    start, end = get_validity_dates(
        document
    )


    # ========================================================
    # Hiç tarih bilgisi yoksa
    # geçerli veya geçersiz diye uydurma.
    # ========================================================

    if (
        start is None
        and end is None
    ):

        return TEMPORAL_UNKNOWN


    # ========================================================
    # Henüz yürürlüğe girmemiş
    # ========================================================

    if (
        start is not None
        and query_date < start
    ):

        return TEMPORAL_INVALID


    # ========================================================
    # Geçerlilik sona ermiş
    # ========================================================

    if (
        end is not None
        and query_date > end
    ):

        return TEMPORAL_INVALID


    # ========================================================
    # Tarih aralığında
    # ========================================================

    return TEMPORAL_VALID


# ============================================================
# BUGÜN İÇİN DEĞERLENDİR
# ============================================================

def evaluate_current(
    document,
    today=None
):

    if today is None:

        today = date.today()


    today = normalize_date_value(
        today
    )


    status = str(
        document.get(
            "status"
        )
        or ""
    ).strip().lower()


    start, end = get_validity_dates(
        document
    )


    # ========================================================
    # Açıkça historical / repealed
    # ========================================================

    if status in HISTORICAL_STATUSES:

        return TEMPORAL_INVALID


    # ========================================================
    # Gelecekte başlayacak
    # ========================================================

    if (
        start is not None
        and today < start
    ):

        return TEMPORAL_INVALID


    # ========================================================
    # Geçerliliği bitmiş
    # ========================================================

    if (
        end is not None
        and today > end
    ):

        return TEMPORAL_INVALID


    # ========================================================
    # Current status + tarih çelişkisi yok
    # ========================================================

    if status in CURRENT_STATUSES:

        return TEMPORAL_VALID


    # ========================================================
    # Status bilinmiyor, tarih bilgisi de yok
    # ========================================================

    if (
        not status
        and not has_temporal_metadata(
            document
        )
    ):

        return TEMPORAL_UNKNOWN


    # ========================================================
    # Status bilinmiyor ama tarih aralığı bugünle uyumlu
    # ========================================================

    if (
        start is not None
        or end is not None
    ):

        return TEMPORAL_VALID


    return TEMPORAL_UNKNOWN


# ============================================================
# ANA TEMPORAL DEĞERLENDİRME
# ============================================================

def evaluate_temporal(
    document,
    mode="neutral",
    query_date=None,
    today=None
):

    # ========================================================
    # NORMAL SORU
    #
    # Temporal filtre uygulanmaz.
    # ========================================================

    if mode == "neutral":

        return TEMPORAL_NEUTRAL


    # ========================================================
    # GÜNCEL SORU
    # ========================================================

    if mode == "current":

        return evaluate_current(
            document=document,
            today=today
        )


    # ========================================================
    # TARİHSEL SORU
    # ========================================================

    if mode == "historical_date":

        return evaluate_on_date(
            document=document,
            query_date=query_date
        )


    raise ValueError(
        f"Bilinmeyen temporal mode: {mode}"
    )


# ============================================================
# TEMPORAL SCORE
# ============================================================

def calculate_temporal_score(
    temporal_result
):

    if temporal_result == TEMPORAL_VALID:

        return 1.0


    if temporal_result == TEMPORAL_NEUTRAL:

        return 1.0


    if temporal_result == TEMPORAL_UNKNOWN:

        # ----------------------------------------------------
        # Bilinmeyen bilgiyi "geçersiz" saymıyoruz,
        # fakat tam güven de vermiyoruz.
        # ----------------------------------------------------

        return 0.5


    if temporal_result == TEMPORAL_INVALID:

        return 0.0


    return 0.0


# ============================================================
# STRICT TEMPORAL FILTER KARARI
# ============================================================

def should_keep_document(
    temporal_result,
    strict=False
):

    # ========================================================
    # Geçersiz olduğu bilinen belgeyi çıkar.
    # ========================================================

    if temporal_result == TEMPORAL_INVALID:

        return False


    # ========================================================
    # Strict modda unknown da çıkarılır.
    #
    # Örneğin:
    # "01.01.2020 tarihinde yürürlükte miydi?"
    #
    # ve belge tarihleri bilinmiyorsa,
    # bunu geçerliymiş gibi kullanmak istemeyebiliriz.
    # ========================================================

    if (
        strict
        and temporal_result
        == TEMPORAL_UNKNOWN
    ):

        return False


    return True


# ============================================================
# DOCUMENT FILTER
# ============================================================

def filter_documents_by_time(
    documents,
    mode="neutral",
    query_date=None,
    today=None,
    strict=False
):

    filtered = []


    for document in documents:

        result = evaluate_temporal(
            document=document,
            mode=mode,
            query_date=query_date,
            today=today
        )


        if should_keep_document(
            temporal_result=result,
            strict=strict
        ):

            filtered.append(
                document
            )


    return filtered


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    print(
        "\n======================================"
    )

    print(
        " VERGİ AI - TEMPORAL POLICY V2 TEST"
    )

    print(
        "======================================"
    )


    # ========================================================
    # TEST BELGELERİ
    # ========================================================

    current_document = {

        "document_id":
            "test_current",

        "status":
            "active",

        "yururluk_tarihi":
            "2022-01-01",

        "gecerlilik_baslangici":
            "2022-01-01",

        "gecerlilik_sonu":
            None,

        "mulga_tarihi":
            None
    }


    historical_document = {

        "document_id":
            "test_historical",

        "status":
            "historical",

        "yururluk_tarihi":
            "2018-01-01",

        "gecerlilik_baslangici":
            "2018-01-01",

        "gecerlilik_sonu":
            "2021-12-31",

        "mulga_tarihi":
            None
    }


    unknown_historical = {

        "document_id":
            "unknown_historical",

        "status":
            "historical",

        "yururluk_tarihi":
            None,

        "gecerlilik_baslangici":
            None,

        "gecerlilik_sonu":
            None,

        "mulga_tarihi":
            None
    }


    # ========================================================
    # QUERY MODE TESTLERİ
    # ========================================================

    queries = [

        (
            "6736 sayılı Kanunun "
            "5. maddesi ne diyor?"
        ),

        (
            "Bu hüküm bugün "
            "yürürlükte mi?"
        ),

        (
            "Bu hüküm 2020 yılında "
            "geçerli miydi?"
        ),

        (
            "Bu hüküm 01.06.2021 tarihinde "
            "geçerli miydi?"
        )
    ]


    print(
        "\nQUERY MODE TESTLERİ"
    )


    for query in queries:

        print(
            "\nSoru:"
        )

        print(
            query
        )

        print(
            "Mode:"
        )

        print(
            get_temporal_mode(
                query
            )
        )


    # ========================================================
    # TEMPORAL EVALUATION
    # ========================================================

    print(
        "\n======================================"
    )

    print(
        " TEMPORAL EVALUATION"
    )

    print(
        "======================================"
    )


    print(
        "\nNormal soru / historical belge:"
    )

    print(
        evaluate_temporal(
            historical_document,
            mode="neutral"
        )
    )


    print(
        "\nBugün / current belge:"
    )

    print(
        evaluate_temporal(
            current_document,
            mode="current"
        )
    )


    print(
        "\nBugün / historical belge:"
    )

    print(
        evaluate_temporal(
            historical_document,
            mode="current"
        )
    )


    print(
        "\n2020 / historical belge:"
    )

    print(
        evaluate_temporal(
            historical_document,
            mode="historical_date",
            query_date="2020-06-01"
        )
    )


    print(
        "\n2020 / current belge:"
    )

    print(
        evaluate_temporal(
            current_document,
            mode="historical_date",
            query_date="2020-06-01"
        )
    )


    print(
        "\n2020 / tarihi bilinmeyen historical belge:"
    )

    print(
        evaluate_temporal(
            unknown_historical,
            mode="historical_date",
            query_date="2020-06-01"
        )
    )