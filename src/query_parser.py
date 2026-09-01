import re


# ============================================================
# VERGİ AI - QUERY METADATA PARSER V4
# ============================================================


def normalize_text(text):

    if not text:
        return ""

    text = str(text)

    text = (
        text
        .replace("’", "'")
        .replace("‘", "'")
        .replace("`", "'")
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ============================================================
# İLK REGEX EŞLEŞMESİ
# ============================================================

def first_match(
    text,
    patterns
):

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:
            return match.group(1)

    return None


# ============================================================
# KANUN NO
# ============================================================

def parse_kanun_no(
    text
):

    patterns = [

        # 6736 sayılı Kanun
        r"\b(\d{3,5})\s+sayılı\b",

        # Kanun No: 6736
        r"\bkanun\s*no\s*[:\-]?\s*(\d{3,5})\b"
    ]

    return first_match(
        text,
        patterns
    )


# ============================================================
# MADDE
# ============================================================

def parse_madde(
    text
):

    # --------------------------------------------------------
    # ÖNCE NUMARA + MADDE
    #
    # 5. madde
    # 5. maddesi
    # 5. maddesinin
    #
    # Bu önce kontrol edilmeli.
    # Çünkü:
    #
    # "5. madde 3. fıkra"
    #
    # içinde "madde 3" ifadesinin yanlışlıkla
    # yakalanmasını engeller.
    # --------------------------------------------------------

    match = re.search(
        r"\b(\d+[A-Za-z]?)\s*\.?\s*madd\w*\b",
        text,
        re.IGNORECASE
    )

    if match:
        return match.group(1)


    # --------------------------------------------------------
    # SONRA MADDE + NUMARA
    #
    # madde 5
    # madde: 5
    # --------------------------------------------------------

    match = re.search(
        r"\bmadde\s*[:\-]?\s*(\d+[A-Za-z]?)\b",
        text,
        re.IGNORECASE
    )

    if match:
        return match.group(1)


    # --------------------------------------------------------
    # KISA HUKUK YAZIMI
    #
    # 5/3
    # 5/3-a
    # --------------------------------------------------------

    match = re.search(
        r"\b(\d+[A-Za-z]?)\s*/\s*\d+",
        text,
        re.IGNORECASE
    )

    if match:
        return match.group(1)


    return None


# ============================================================
# FIKRA
# ============================================================

def parse_fikra(
    text
):

    # --------------------------------------------------------
    # ÖNCE FIKRA + NUMARA
    #
    # fıkra 3
    #
    # Bu özellikle:
    #
    # madde 5 fıkra 3
    #
    # biçiminde 5'in yanlışlıkla fıkra
    # olarak alınmasını engeller.
    # --------------------------------------------------------

    match = re.search(
        r"\bfıkra\s*[:\-]?\s*(\d+)\b",
        text,
        re.IGNORECASE
    )

    if match:
        return match.group(1)


    # --------------------------------------------------------
    # SONRA NUMARA + FIKRA
    #
    # 3. fıkra
    # 3. fıkrası
    # 3. fıkrasının
    # --------------------------------------------------------

    match = re.search(
        r"\b(\d+)\s*\.?\s*fıkra\w*\b",
        text,
        re.IGNORECASE
    )

    if match:
        return match.group(1)


    # --------------------------------------------------------
    # KISA HUKUK YAZIMI
    #
    # 5/3
    # 5/3-a
    # --------------------------------------------------------

    match = re.search(
        r"\b\d+[A-Za-z]?\s*/\s*(\d+)",
        text,
        re.IGNORECASE
    )

    if match:
        return match.group(1)


    return None


# ============================================================
# BENT
# ============================================================

def parse_bent(
    text
):

    patterns = [

        # bent b
        # bent: b
        r"\bbent\s*[:\-]?\s*([a-zçğıöşü])\b",

        # (b) bendi
        # (a) bendinin
        r"\(\s*([a-zçğıöşü])\s*\)\s*bend\w*\b",

        # b bendi
        # a bendindeki
        r"\b([a-zçğıöşü])\s+bend\w*\b"
    ]


    value = first_match(
        text,
        patterns
    )


    if value is not None:
        return value.lower()


    # --------------------------------------------------------
    # KISA HUKUK YAZIMI
    #
    # 5/3-a
    # 5/3/a
    # --------------------------------------------------------

    match = re.search(
        r"\b\d+[A-Za-z]?\s*/\s*\d+\s*[-/]\s*([a-zçğıöşü])\b",
        text,
        re.IGNORECASE
    )

    if match:

        return (
            match.group(1)
            .lower()
        )


    return None


# ============================================================
# ANA PARSER
# ============================================================

def parse_query_metadata(
    query
):

    text = normalize_text(
        query
    )

    return {

        "kanun_no":
            parse_kanun_no(
                text
            ),

        "madde":
            parse_madde(
                text
            ),

        "fikra":
            parse_fikra(
                text
            ),

        "bent":
            parse_bent(
                text
            )
    }


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    print(
        "\n======================================"
    )

    print(
        " VERGİ AI - QUERY PARSER V4 TEST"
    )

    print(
        "======================================"
    )


    test_queries = [

        (
            "6736 sayılı Kanunun "
            "5. maddesinin 3. fıkrasında "
            "KDV artırımı ne diyor?"
        ),

        (
            "6736 sayılı Kanunun "
            "5. maddesinin 3. fıkrasının "
            "a bendindeki KDV artırım "
            "oranları nelerdir?"
        ),

        (
            "6736 sayılı Kanun "
            "madde 5 fıkra 3 bent b"
        ),

        (
            "6736 sayılı Kanun "
            "5/3-a hükmü nedir?"
        ),

        (
            "6736 sayılı Kanun "
            "5. madde 3. fıkra (b) bendi"
        ),

        (
            "6736 sayılı Kanunun "
            "99. maddesi ne diyor?"
        ),

        (
            "213 sayılı Vergi Usul "
            "Kanununun 359. maddesi "
            "ne diyor?"
        )
    ]


    for number, query in enumerate(
        test_queries,
        start=1
    ):

        print(
            "\n--------------------------------------"
        )

        print(
            f"TEST {number}"
        )

        print(
            query
        )

        print(
            parse_query_metadata(
                query
            )
        )