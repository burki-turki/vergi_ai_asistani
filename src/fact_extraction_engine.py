# ============================================================
# VERGİ AI - FACT EXTRACTION ENGINE V1.3
#
# AMAÇ:
#
# Case document metninden LLM kullanarak yapılandırılmış
# fact extraction üretmek.
#
#
# V1.3:
#
# 1. Document ID seçimi LLM'den kaldırılmıştır.
# 2. Document Reference Resolver V1 entegredir.
# 3. related_document_ids deterministik oluşturulur.
# 4. Belge türüne göre claim/procedural fact ayrımı yapılır.
# 5. LLM teknik/internal warning mesajları temizlenir.
#
# YENİ:
#
# 6. SOURCE ATTRIBUTION LOCK
#
#    Dava dilekçesi gibi pleading belgelerde fact'in epistemik
#    kaynağı belgenin issuer party'sidir.
#
#    Örnek:
#
#    Dava dilekçesi:
#    "İhbarnamede 850.000 TL KDV tarh edilmiştir."
#
#    attributed_party_id:
#        party_taxpayer_001
#
#    attributed_actor_label:
#        ABC Ltd. Şti. - Demo
#
#    Vergi Dairesi fact'in konusu/related party'si olabilir,
#    fakat mevcut belgedeki beyanın kaynağı değildir.
#
#
# 7. EVIDENTIARY OVERCLAIM GUARD
#
#    Kaynak:
#
#        Dava Tarihi: 05.03.2026
#
#    bundan:
#
#        "Dava 05.03.2026 tarihinde mahkemeye sunulmuştur."
#
#    sonucu çıkarılamaz.
#
#    Deterministik guard bunu:
#
#        "Dava dilekçesinde dava tarihi 05.03.2026
#         olarak belirtilmiştir."
#
#    şeklinde sınırlar.
#
#
# PIPELINE:
#
# document text
#      ↓
# LLM
#      ↓
# raw facts
#      ↓
# deterministic normalization
#      ↓
# Source Attribution Lock
#      ↓
# Evidentiary Overclaim Guard
#      ↓
# Document Reference Resolver V1
#      ↓
# Warning Hygiene
#      ↓
# Case Fact Validator
#      ↓
# *.json.pending
#
#
# TEMEL PRENSİP:
#
# BELGEDE YAZAN
#      !=
# DOĞRULANMIŞ MADDİ GERÇEK
#
# APPROVAL
#      !=
# VERIFICATION
# ============================================================


import argparse
import json
import os
import re

from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

from case_fact_validator import (
    validate_fact_extraction,
)

from document_reference_resolver import (
    DocumentReferenceResolver,
)


# ============================================================
# VERSION
# ============================================================

FACT_EXTRACTION_ENGINE_VERSION = "1.3"

PROMPT_VERSION = "fact_extraction_v1_3"

DEFAULT_MODEL = "claude-sonnet-4-6"

MAX_INPUT_CHARS = 60000


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

DEFAULT_CASE_ID = "case_0001"

DEFAULT_DOCUMENT_ID = "vir_001"

DEFAULT_TEXT_PATH = (
    DATA_DIR
    / "cases"
    / DEFAULT_CASE_ID
    / "documents"
    / DEFAULT_DOCUMENT_ID
    / "extracted"
    / "vir_001.txt"
)


# ============================================================
# ENV
# ============================================================

load_dotenv(
    BASE_DIR / ".env"
)


# ============================================================
# CONSTANTS
# ============================================================

FACT_KINDS = {
    "event",
    "administrative_claim",
    "taxpayer_claim",
    "document_finding",
    "transaction",
    "payment",
    "monetary_fact",
    "date_fact",
    "party_fact",
    "legal_reference",
    "procedural_fact",
    "evidence_reference",
    "other",
}


EXTRACTION_BASES = {
    "explicit_text",
    "table",
    "document_metadata",
    "document_structure",
    "derived",
    "unknown",
}


VALUE_TYPES = {
    "string",
    "number",
    "date",
    "money",
    "reference",
}


SOURCE_AUTHORED_FACT_KINDS = {
    "administrative_claim",
    "taxpayer_claim",
    "document_finding",
    "legal_reference",
    "procedural_fact",
    "date_fact",
    "event",
    "monetary_fact",
    "evidence_reference",
}


# ============================================================
# PLEADING DOCUMENT TYPES
# ============================================================

PLEADING_DOCUMENT_TYPES = {
    "dava_dilekcesi",
    "cevap_dilekcesi",
    "savunma_dilekcesi",
    "istinaf_dilekcesi",
    "temyiz_dilekcesi",
    "ek_beyan_dilekcesi",
}


PLEADING_DOCUMENT_CATEGORIES = {
    "pleading",
    "court_filing",
    "judicial_filing",
}


# ============================================================
# META / TEST PHRASES
# ============================================================

META_TEST_PHRASES = {
    "sentetik test verisi",
    "geliştirme sürecinde kullanılmak üzere",
    "gerçek bir vergi inceleme raporu değildir",
    "gerçek bir vergi/ceza ihbarnamesi değildir",
    "gerçek bir ihbarname değildir",
    "gerçek bir dava dilekçesi değildir",
    "demo niteliğindedir",
}


# ============================================================
# UNSUPPORTED FILING ASSERTIONS
# ============================================================

FILING_ASSERTION_PHRASES = (
    "mahkemeye sunulmuştur",
    "mahkemeye sunuldu",
    "mahkemeye verilmiştir",
    "mahkemeye verildi",
    "mahkemeye tevdi edilmiştir",
    "tevdi edilmiştir",
    "dava açılmıştır",
    "dava açıldı",
    "kayda alınmıştır",
    "esas kaydına alınmıştır",
)


# ============================================================
# JSON
# ============================================================

def load_json(path):

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:

        return json.load(file)


def write_json(
    path,
    data,
):

    path = Path(
        path
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with open(
        path,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# TEXT
# ============================================================

def load_text(path):

    path = Path(
        path
    )

    if not path.exists():

        raise FileNotFoundError(
            "Belge metni bulunamadı:\n"
            f"{path}"
        )

    with open(
        path,
        "r",
        encoding="utf-8-sig",
    ) as file:

        text = file.read()

    if not text.strip():

        raise ValueError(
            "Belge metni boş."
        )

    if len(text) > MAX_INPUT_CHARS:

        raise ValueError(
            "Belge metni Fact Extraction Engine V1.3 "
            "tek çağrı sınırını aşıyor.\n"
            f"Karakter: {len(text)}\n"
            f"Sınır: {MAX_INPUT_CHARS}"
        )

    return text


# ============================================================
# CASE CONTEXT
# ============================================================

def load_case_context(
    case_id,
    document_id,
):

    case_dir = (
        DATA_DIR
        / "cases"
        / case_id
    )

    case_path = (
        case_dir
        / "case.json"
    )

    document_path = (
        case_dir
        / "documents"
        / document_id
        / "document.json"
    )

    if not case_path.exists():

        raise FileNotFoundError(
            "case.json bulunamadı:\n"
            f"{case_path}"
        )

    if not document_path.exists():

        raise FileNotFoundError(
            "document.json bulunamadı:\n"
            f"{document_path}"
        )

    case_data = load_json(
        case_path
    )

    document_data = load_json(
        document_path
    )

    if (
        case_data.get(
            "case_id"
        )
        != case_id
    ):

        raise ValueError(
            "case.json case_id eşleşmiyor."
        )

    if (
        document_data.get(
            "document_id"
        )
        != document_id
    ):

        raise ValueError(
            "document.json document_id eşleşmiyor."
        )

    if (
        document_data.get(
            "case_id"
        )
        != case_id
    ):

        raise ValueError(
            "document.json case_id eşleşmiyor."
        )

    return (
        case_data,
        document_data,
        case_dir,
    )


# ============================================================
# PARTY
# ============================================================

def find_party(
    case_data,
    party_id,
):

    if not party_id:

        return None

    for party in case_data.get(
        "parties",
        [],
    ):

        if (
            party.get(
                "party_id"
            )
            == party_id
        ):

            return party

    return None


# ============================================================
# SOURCE ACTOR
# ============================================================

def determine_source_actor_label(
    case_data,
    document_data,
):

    issuer_party_id = (
        document_data.get(
            "issuer_party_id"
        )
    )

    issuer_party = find_party(
        case_data,
        issuer_party_id,
    )

    if issuer_party:

        display_name = (
            issuer_party.get(
                "display_name"
            )
        )

        if display_name:

            return display_name

    for reference in document_data.get(
        "reference_numbers",
        [],
    ):

        issuing_body = (
            reference.get(
                "issuing_body"
            )
        )

        if issuing_body:

            return issuing_body

    return None


# ============================================================
# PLEADING DETECTION
# ============================================================

def is_pleading_document(
    context,
):

    document_type = (
        context.get(
            "source_document_type"
        )
        or ""
    ).casefold()

    document_category = (
        context.get(
            "source_document_category"
        )
        or ""
    ).casefold()

    if (
        document_type
        in PLEADING_DOCUMENT_TYPES
    ):

        return True

    if (
        document_category
        in PLEADING_DOCUMENT_CATEGORIES
    ):

        return True

    return False


# ============================================================
# ALLOWED CONTEXT
# ============================================================

def build_allowed_context(
    case_data,
    document_data,
):

    parties = []

    for party in case_data.get(
        "parties",
        [],
    ):

        parties.append(
            {
                "party_id":
                    party.get(
                        "party_id"
                    ),

                "role":
                    party.get(
                        "role"
                    ),

                "display_name":
                    party.get(
                        "display_name"
                    ),
            }
        )

    dispute_items = []

    for item in case_data.get(
        "dispute_items",
        [],
    ):

        dispute_items.append(
            {
                "dispute_item_id":
                    item.get(
                        "dispute_item_id"
                    ),

                "tax_type":
                    item.get(
                        "tax_type"
                    ),

                "period":
                    item.get(
                        "period"
                    ),

                "asserted_legal_basis_refs":
                    item.get(
                        "asserted_legal_basis_refs",
                        [],
                    ),
            }
        )

    return {
        "case_id":
            case_data.get(
                "case_id"
            ),

        "source_document_id":
            document_data.get(
                "document_id"
            ),

        "source_document_title":
            document_data.get(
                "title"
            ),

        "source_document_category":
            document_data.get(
                "document_category"
            ),

        "source_document_type":
            document_data.get(
                "document_type"
            ),

        "source_document_subtype":
            document_data.get(
                "document_subtype"
            ),

        "source_document_issuer_party_id":
            document_data.get(
                "issuer_party_id"
            ),

        "source_actor_label":
            determine_source_actor_label(
                case_data,
                document_data,
            ),

        "parties":
            parties,

        "dispute_items":
            dispute_items,
    }


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """
Sen vergi uyuşmazlığı dosyalarında belge içeriğinden olgusal bilgi
çıkaran bir Fact Extraction Engine'sin.

Görevin HUKUKİ KARAR VERMEK DEĞİLDİR.

Sadece kaynak belgede açıkça bulunan veya belgenin yapısından
doğrudan çıkarılabilen bilgileri yapılandır.


============================================================
TEMEL KURAL
============================================================

BELGEDE YAZAN
!=
MADDİ GERÇEĞİN DOĞRULANDIĞI


============================================================
BELGE TÜRÜ SEMANTİĞİ
============================================================

Belge türünü mutlaka dikkate al.


------------------------------------------------------------
VERGİ İNCELEME RAPORU
------------------------------------------------------------

Örnek:

"850.000 TL haksız KDV indirimi yapıldığı kanaatine varılmıştır."

Bu:

administrative_claim

olmalıdır.

Çünkü inceleme makamının değerlendirmesini/kanaatini gösterir.


------------------------------------------------------------
VERGİ / CEZA İHBARNAMESİ
------------------------------------------------------------

Örnek:

"850.000 TL KDV tarh edilmiştir."

İhbarname bir idari işlem belgesidir.

Bu nedenle:

procedural_fact

veya gerektiğinde:

document_finding

olarak modelle.

Şöyle yaz:

"İhbarnamede mükellef adına 850.000 TL KDV tarh edildiği
belirtilmektedir."

Şöyle yazma:

"İnceleme makamı tarh edildiğini ileri sürmektedir."


------------------------------------------------------------
DAVA DİLEKÇESİ
------------------------------------------------------------

Dava dilekçesi:

davacının beyan ve iddialarını içeren bir pleading belgedir.

Örnek:

"İndirim konusu yapılan KDV gerçek mal ve hizmet
alımlarına dayanmaktadır."

Bu:

taxpayer_claim

olmalıdır.

Örnek:

"Vergi ziyaı cezası kesilmesini gerektiren şartlar oluşmamıştır."

Bu:

taxpayer_claim

olmalıdır.

Örnek:

"VUK 341'e dayanılarak yapılan değerlendirme hukuka uygun değildir."

Bu AI'ın hukuki sonucu değildir.

Şöyle modelle:

"Davacı, VUK 341'e dayanılarak yapılan değerlendirmenin
hukuka uygun olmadığını iddia etmektedir."

fact_kind:

taxpayer_claim


============================================================
SOURCE ATTRIBUTION
============================================================

attributed_party_id:

fact'in sadece KONUSUNU değil,
MEVCUT KAYNAK BELGEDEKİ beyanın / işlemin / iddianın
epistemik kaynağını temsil eder.


ÖNEMLİ:

Dava dilekçesi gibi pleading belgelerde kaynak actor,
belgeyi sunan/düzenleyen taraftır.

Örneğin dava dilekçesinde:

"İhbarnamede 850.000 TL KDV tarh edilmiştir."

yazıyorsa:

bu fact'in mevcut kaynak belgesi dava dilekçesidir.

Dolayısıyla attribution:

davacıya aittir.

Vergi Dairesi:

related_party_ids içinde bulunabilir.

Ama attributed_actor_label olarak otomatik seçilmemelidir.


SOURCE DOCUMENT ISSUER PARTY ID varsa:

özellikle pleading belgelerde source attribution için
bu issuer party esas alınmalıdır.


SOURCE DOCUMENT ISSUER PARTY ID null ise:

case içindeki başka bir tarafı tahmin ederek attribution yapma.

Bu durumda:

attributed_party_id = null

ve gerekiyorsa:

attributed_actor_label

kullan.


============================================================
EVIDENTIARY OVERCLAIM
============================================================

Kaynak metinde olmayan usuli sonucu üretme.

Özellikle:

"Dava Tarihi: 05.03.2026"

ifadesi TEK BAŞINA:

"Dava 05.03.2026 tarihinde mahkemeye sunulmuştur."

"Dava 05.03.2026 tarihinde açılmıştır."

"Dilekçe 05.03.2026 tarihinde mahkemeye verilmiştir."

sonuçlarını desteklemez.

Böyle bir durumda yalnız:

"Dava dilekçesinde dava tarihi 05.03.2026 olarak belirtilmiştir."

şeklinde fact çıkar.

Tercihen:

fact_kind = date_fact

kullan.

Mahkemeye sunulma, dava açma, tevdi veya kayıt tarihi
ancak kaynak metin bunu açıkça söylüyorsa çıkarılabilir.


============================================================
DOCUMENT REFERENCES
============================================================

ÇOK ÖNEMLİ:

Sen document_id BELİRLEYEMEZSİN.

related_document_ids alanını HER ZAMAN:

[]

olarak döndür.

Örneğin:

"VIR-DEMO-2026-001 sayılı Vergi İnceleme Raporu"

geçiyorsa:

structured_values içinde:

{
  "value_type": "reference",
  "label": "Vergi İnceleme Raporu No",
  "reference_value": "VIR-DEMO-2026-001"
}

şeklinde çıkar.

Ama:

related_document_ids = ["vir_001"]

YAZMA.

Document ID eşlemesini deterministic
Document Reference Resolver yapacaktır.


============================================================
LEGAL REFERENCES
============================================================

Belgede kanun/madde açıkça yazıyorsa legal_reference çıkarılabilir.

Örneğin:

3065 sayılı KDV Kanunu m.29

belgede geçiyorsa:

reference_value = "KDVK_m29"

kullanılabilir; ancak yalnız CASE CONTEXT içindeki
asserted_legal_basis_refs ile açıkça eşleşiyorsa.

Bir kanun maddesinin belgede yazması:

- hukuken doğru olduğu,
- olay tarihinde yürürlükte olduğu,
- olaya uygulanabilir olduğu

anlamına gelmez.


Dava dilekçesinde kanun maddesine dayanılarak bir
hukuki sonuç ileri sürülüyorsa:

bunu davacının iddiası olarak modelle.


============================================================
MONEY
============================================================

Para değerlerini structured_values içinde money olarak çıkar.

Örneğin:

850.000,00 TL

için:

{
  "amount": "850000.00",
  "currency": "TRY"
}

kullan.


============================================================
SOURCE
============================================================

Kaynak sayfa bilinmiyorsa:

page = null

source.text_excerpt:

kaynak belgedeki kısa ve sadık alıntı olmalıdır.

Kaynak metinde olmayan bir olay veya eylem uydurma.


============================================================
CONFIDENCE / VERIFICATION
============================================================

confidence:

yalnız extraction güvenidir.

verification_state:

HER FACT İÇİN:

"unverified"

olmalıdır.

Sen hiçbir fact'i verified yapamazsın.


============================================================
META / TEST DATA
============================================================

Belgenin:

- sentetik,
- demo,
- test,
- Vergi AI geliştirme amacıyla oluşturulmuş

olduğunu belirten teknik açıklamaları CASE FACT olarak çıkarma.


============================================================
ATOMICITY
============================================================

Mümkün olduğunca atomik fact üret.

Bir fact:

bir temel olay,
bir işlem,
bir iddia,
bir tarih,
bir tutar,
bir belge ilişkisi
veya bir hukuki atıf

temsil etmelidir.


============================================================
YASAK
============================================================

AI'ın kendi sonucu olarak şunları üretme:

- hukuka aykırıdır
- hukuka uygundur
- dava kazanılır
- ceza iptal edilmelidir
- tarhiyat geçersizdir
- zamanaşımı vardır
- süre kaçırılmıştır
- mükellef suç işlemiştir


Bir taraf kaynak belgede bunları ileri sürüyorsa:

yalnız ilgili tarafın iddiası olarak modelleyebilirsin.


============================================================
OUTPUT
============================================================

Sadece JSON döndür.

{
  "facts": [
    {
      "fact_kind": "...",
      "statement": "...",
      "normalized_statement": null,
      "extraction_basis": "...",
      "attributed_party_id": null,
      "attributed_actor_label": null,
      "source": {
        "page": null,
        "section": null,
        "paragraph": null,
        "text_excerpt": null
      },
      "structured_values": [],
      "related_party_ids": [],
      "related_document_ids": [],
      "related_dispute_item_ids": [],
      "confidence": 0.0,
      "verification_state": "unverified",
      "notes": null
    }
  ],
  "warnings": []
}


fact_kind:

event
administrative_claim
taxpayer_claim
document_finding
transaction
payment
monetary_fact
date_fact
party_fact
legal_reference
procedural_fact
evidence_reference
other


extraction_basis:

explicit_text
table
document_metadata
document_structure
derived
unknown


structured value_type:

string
number
date
money
reference


Her structured_value şu alanların tamamını içermelidir:

value_type
label
string_value
number_value
date_value
money_value
reference_value

Kullanılmayan alanlar null olmalıdır.
"""


# ============================================================
# USER PROMPT
# ============================================================

def build_user_prompt(
    context,
    document_text,
):

    context_json = json.dumps(
        context,
        ensure_ascii=False,
        indent=2,
    )

    return f"""
CASE CONTEXT
============

{context_json}


SOURCE DOCUMENT TEXT
====================

{document_text}


TASK
====

Kaynak belgeden desteklenen case fact kayıtlarını çıkar.

Belge türünü dikkate al:

source_document_category
source_document_type
source_document_subtype

alanları önemlidir.

Vergi İnceleme Raporundaki iddia/kanaat ile
İhbarnamedeki tesis edilmiş idari işlem ile
Dava Dilekçesindeki taraf iddiasını birbirine karıştırma.

Dava dilekçesindeki davacı beyanlarını taxpayer_claim olarak
doğru attribution ile modelle.

Kaynak yalnız:

"Dava Tarihi: DD.MM.YYYY"

diyorsa mahkemeye sunulma veya dava açılma olayını uydurma.

Document ID seçme.

related_document_ids alanlarını daima [] döndür.

Belge numaralarını reference structured value olarak çıkar.

Sentetik/demo/development açıklamalarını fact olarak çıkarma.

Sadece JSON döndür.
"""


# ============================================================
# ANTHROPIC
# ============================================================

def call_llm(
    prompt,
    model,
):

    api_key = os.getenv(
        "ANTHROPIC_API_KEY"
    )

    if not api_key:

        raise RuntimeError(
            "ANTHROPIC_API_KEY bulunamadı. "
            ".env dosyasını kontrol et."
        )

    client = Anthropic(
        api_key=api_key
    )

    response = (
        client.messages.create(
            model=model,
            max_tokens=6000,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role":
                        "user",

                    "content":
                        prompt,
                }
            ],
        )
    )

    text_parts = []

    for block in response.content:

        if getattr(
            block,
            "type",
            None,
        ) == "text":

            text_parts.append(
                block.text
            )

    result = "\n".join(
        text_parts
    ).strip()

    if not result:

        raise ValueError(
            "LLM boş cevap döndürdü."
        )

    return result


# ============================================================
# JSON PARSER
# ============================================================

def parse_llm_json(text):

    cleaned = text.strip()

    fence_match = re.search(
        r"```(?:json)?\s*(.*?)```",
        cleaned,
        flags=(
            re.DOTALL
            | re.IGNORECASE
        ),
    )

    if fence_match:

        cleaned = (
            fence_match
            .group(1)
            .strip()
        )

    try:

        parsed = json.loads(
            cleaned
        )

        if isinstance(
            parsed,
            dict,
        ):

            return parsed

    except json.JSONDecodeError:

        pass

    start = cleaned.find(
        "{"
    )

    end = cleaned.rfind(
        "}"
    )

    if (
        start >= 0
        and end > start
    ):

        candidate = cleaned[
            start:
            end + 1
        ]

        parsed = json.loads(
            candidate
        )

        if isinstance(
            parsed,
            dict,
        ):

            return parsed

    raise ValueError(
        "LLM çıktısından geçerli JSON "
        "nesnesi çıkarılamadı."
    )


# ============================================================
# CONFIDENCE
# ============================================================

def clamp_confidence(value):

    try:

        number = float(
            value
        )

    except (
        TypeError,
        ValueError,
    ):

        return 0.5

    return max(
        0.0,
        min(
            number,
            1.0,
        ),
    )


# ============================================================
# SOURCE
# ============================================================

def normalize_source(
    source,
):

    if not isinstance(
        source,
        dict,
    ):

        source = {}

    page = source.get(
        "page"
    )

    if not isinstance(
        page,
        int,
    ):

        page = None

    return {
        "page":
            page,

        "section":
            source.get(
                "section"
            ),

        "paragraph":
            source.get(
                "paragraph"
            ),

        "text_excerpt":
            source.get(
                "text_excerpt"
            ),
    }


# ============================================================
# MONEY
# ============================================================

def parse_decimal_amount(
    amount,
):

    if amount is None:

        return None

    text = str(
        amount
    ).strip()

    text = text.replace(
        " ",
        "",
    )

    try:

        return Decimal(
            text
        )

    except InvalidOperation:

        pass

    if "," in text:

        try:

            normalized = (
                text
                .replace(
                    ".",
                    "",
                )
                .replace(
                    ",",
                    ".",
                )
            )

            return Decimal(
                normalized
            )

        except InvalidOperation:

            return None

    return None


def normalize_money(
    value,
):

    if not isinstance(
        value,
        dict,
    ):

        return None

    amount = value.get(
        "amount"
    )

    currency = value.get(
        "currency"
    )

    if (
        amount is None
        or currency is None
    ):

        return None

    decimal_amount = (
        parse_decimal_amount(
            amount
        )
    )

    if decimal_amount is None:

        return None

    decimal_amount = (
        decimal_amount.quantize(
            Decimal("0.01")
        )
    )

    return {
        "amount":
            format(
                decimal_amount,
                ".2f",
            ),

        "currency":
            str(
                currency
            ).upper(),
    }


# ============================================================
# STRUCTURED VALUES
# ============================================================

def normalize_structured_value(
    value,
):

    if not isinstance(
        value,
        dict,
    ):

        return None

    value_type = value.get(
        "value_type"
    )

    if value_type not in VALUE_TYPES:

        return None

    result = {
        "value_type":
            value_type,

        "label":
            value.get(
                "label"
            ),

        "string_value":
            None,

        "number_value":
            None,

        "date_value":
            None,

        "money_value":
            None,

        "reference_value":
            None,
    }

    if value_type == "string":

        raw = value.get(
            "string_value"
        )

        if raw is not None:

            result[
                "string_value"
            ] = str(
                raw
            )

    elif value_type == "number":

        raw = value.get(
            "number_value"
        )

        if isinstance(
            raw,
            (
                int,
                float,
            ),
        ):

            result[
                "number_value"
            ] = raw

    elif value_type == "date":

        result[
            "date_value"
        ] = value.get(
            "date_value"
        )

    elif value_type == "money":

        result[
            "money_value"
        ] = normalize_money(
            value.get(
                "money_value"
            )
        )

    elif value_type == "reference":

        result[
            "reference_value"
        ] = value.get(
            "reference_value"
        )

    return result


# ============================================================
# ALLOWED IDS
# ============================================================

def filter_allowed_ids(
    values,
    allowed,
):

    if not isinstance(
        values,
        list,
    ):

        return []

    allowed_set = set(
        allowed
    )

    result = []

    for value in values:

        if (
            isinstance(
                value,
                str,
            )
            and value in allowed_set
            and value not in result
        ):

            result.append(
                value
            )

    return result


# ============================================================
# PARTY MAP
# ============================================================

def build_party_map(
    context,
):

    result = {}

    for party in context.get(
        "parties",
        [],
    ):

        party_id = party.get(
            "party_id"
        )

        if party_id:

            result[
                party_id
            ] = party

    return result


# ============================================================
# PARTY NAME CHECK
# ============================================================

def text_contains_party_name(
    raw_fact,
    party,
):

    display_name = (
        party.get(
            "display_name"
        )
    )

    if not display_name:

        return False

    source = raw_fact.get(
        "source",
        {},
    )

    if not isinstance(
        source,
        dict,
    ):

        source = {}

    combined = " ".join(
        [
            str(
                raw_fact.get(
                    "statement",
                    "",
                )
            ),

            str(
                source.get(
                    "text_excerpt",
                    "",
                )
            ),
        ]
    ).casefold()

    return (
        display_name.casefold()
        in combined
    )


# ============================================================
# SOURCE ATTRIBUTION LOCK - V1.3
# ============================================================

def get_locked_source_attribution(
    context,
):

    if not is_pleading_document(
        context
    ):

        return None

    party_map = build_party_map(
        context
    )

    issuer_party_id = (
        context.get(
            "source_document_issuer_party_id"
        )
    )

    if (
        not issuer_party_id
        or issuer_party_id
        not in party_map
    ):

        return None

    party = party_map[
        issuer_party_id
    ]

    actor_label = (
        context.get(
            "source_actor_label"
        )
        or party.get(
            "display_name"
        )
    )

    return (
        issuer_party_id,
        actor_label,
    )


# ============================================================
# ATTRIBUTION
# ============================================================

def normalize_attribution(
    raw_fact,
    context,
):

    party_map = build_party_map(
        context
    )

    fact_kind = (
        raw_fact.get(
            "fact_kind"
        )
    )

    source_issuer_party_id = (
        context.get(
            "source_document_issuer_party_id"
        )
    )

    source_actor_label = (
        context.get(
            "source_actor_label"
        )
    )

    # ========================================================
    # V1.3 SOURCE ATTRIBUTION LOCK
    #
    # Pleading belge ise attribution LLM'e bırakılmaz.
    #
    # Mevcut belgedeki fact'in epistemik kaynağı
    # document issuer'dır.
    # ========================================================

    locked = (
        get_locked_source_attribution(
            context
        )
    )

    if locked is not None:

        return locked

    # ========================================================
    # NORMAL / NON-PLEADING ATTRIBUTION
    # ========================================================

    raw_party_id = (
        raw_fact.get(
            "attributed_party_id"
        )
    )

    raw_label = (
        raw_fact.get(
            "attributed_actor_label"
        )
    )

    if (
        raw_party_id
        not in party_map
    ):

        raw_party_id = None

    if raw_party_id:

        party = (
            party_map[
                raw_party_id
            ]
        )

        role = party.get(
            "role"
        )

        if role == "administration":

            if (
                source_issuer_party_id
                == raw_party_id
            ):

                pass

            elif text_contains_party_name(
                raw_fact,
                party,
            ):

                pass

            else:

                raw_party_id = None

    if (
        raw_party_id is None
        and fact_kind
        in SOURCE_AUTHORED_FACT_KINDS
        and not raw_label
        and source_actor_label
    ):

        raw_label = (
            source_actor_label
        )

    if (
        raw_party_id is None
        and source_issuer_party_id
        and source_issuer_party_id
        in party_map
        and fact_kind
        in SOURCE_AUTHORED_FACT_KINDS
    ):

        raw_party_id = (
            source_issuer_party_id
        )

        if not raw_label:

            raw_label = (
                source_actor_label
            )

    return (
        raw_party_id,
        raw_label,
    )


# ============================================================
# META / TEST FILTER
# ============================================================

def is_meta_test_fact(
    raw_fact,
):

    if not isinstance(
        raw_fact,
        dict,
    ):

        return False

    source = raw_fact.get(
        "source",
        {},
    )

    if not isinstance(
        source,
        dict,
    ):

        source = {}

    combined = " ".join(
        [
            str(
                raw_fact.get(
                    "statement",
                    "",
                )
            ),

            str(
                raw_fact.get(
                    "normalized_statement",
                    "",
                )
            ),

            str(
                source.get(
                    "text_excerpt",
                    "",
                )
            ),
        ]
    ).casefold()

    for phrase in META_TEST_PHRASES:

        if (
            phrase.casefold()
            in combined
        ):

            return True

    return False


# ============================================================
# WARNING HYGIENE
# ============================================================

def normalize_llm_warnings(
    raw_warnings,
):

    if not isinstance(
        raw_warnings,
        list,
    ):

        return []

    ignored_phrases = (
        "related_document_ids",
        "sentetik/demo/test",
        "sentetik test",
        "sentetik/demo",
        "fact olarak çıkarılmamıştır",
        "fact olarak çıkarılmadı",
        "kural gereği fact",
        "kural 18 gereği",
        "document id seçilmemiştir",
        "document id seçilmedi",
    )

    results = []

    for warning in raw_warnings:

        text = str(
            warning
        ).strip()

        if not text:

            continue

        normalized = (
            text.casefold()
        )

        if any(
            phrase.casefold()
            in normalized
            for phrase
            in ignored_phrases
        ):

            continue

        if text not in results:

            results.append(
                text
            )

    return results


# ============================================================
# NOTES
# ============================================================

def append_note(
    existing,
    new_note,
):

    if not new_note:

        return existing

    if not existing:

        return new_note

    existing_text = str(
        existing
    ).strip()

    new_text = str(
        new_note
    ).strip()

    if not existing_text:

        return new_text

    if (
        new_text.casefold()
        in existing_text.casefold()
    ):

        return existing_text

    return (
        existing_text
        + " "
        + new_text
    )


# ============================================================
# NORMALIZE FACT
# ============================================================

def normalize_fact(
    raw_fact,
    fact_id,
    context,
):

    if not isinstance(
        raw_fact,
        dict,
    ):

        return None

    if is_meta_test_fact(
        raw_fact
    ):

        return None

    statement = raw_fact.get(
        "statement"
    )

    if (
        not isinstance(
            statement,
            str,
        )
        or not statement.strip()
    ):

        return None

    fact_kind = raw_fact.get(
        "fact_kind"
    )

    if fact_kind not in FACT_KINDS:

        fact_kind = "other"

    extraction_basis = (
        raw_fact.get(
            "extraction_basis"
        )
    )

    if (
        extraction_basis
        not in EXTRACTION_BASES
    ):

        extraction_basis = "unknown"

    party_ids = [
        party.get(
            "party_id"
        )
        for party in context.get(
            "parties",
            [],
        )
        if party.get(
            "party_id"
        )
    ]

    dispute_item_ids = [
        item.get(
            "dispute_item_id"
        )
        for item in context.get(
            "dispute_items",
            [],
        )
        if item.get(
            "dispute_item_id"
        )
    ]

    (
        attributed_party_id,
        attributed_actor_label,
    ) = normalize_attribution(
        raw_fact,
        context,
    )

    structured_values = []

    raw_values = raw_fact.get(
        "structured_values",
        [],
    )

    if isinstance(
        raw_values,
        list,
    ):

        for raw_value in raw_values:

            normalized = (
                normalize_structured_value(
                    raw_value
                )
            )

            if normalized is not None:

                structured_values.append(
                    normalized
                )

    return {
        "fact_id":
            fact_id,

        "fact_kind":
            fact_kind,

        "statement":
            statement.strip(),

        "normalized_statement":
            raw_fact.get(
                "normalized_statement"
            ),

        "extraction_basis":
            extraction_basis,

        "attributed_party_id":
            attributed_party_id,

        "attributed_actor_label":
            attributed_actor_label,

        "source":
            normalize_source(
                raw_fact.get(
                    "source"
                )
            ),

        "structured_values":
            structured_values,

        "related_party_ids":
            filter_allowed_ids(
                raw_fact.get(
                    "related_party_ids"
                ),
                party_ids,
            ),

        # ----------------------------------------------------
        # LLM document_id belirleyemez.
        # ----------------------------------------------------

        "related_document_ids":
            [],

        "related_dispute_item_ids":
            filter_allowed_ids(
                raw_fact.get(
                    "related_dispute_item_ids"
                ),
                dispute_item_ids,
            ),

        "confidence":
            clamp_confidence(
                raw_fact.get(
                    "confidence"
                )
            ),

        "verification_state":
            "unverified",

        "notes":
            raw_fact.get(
                "notes"
            ),
    }


# ============================================================
# DATE HELPERS
# ============================================================

def get_first_structured_date(
    fact,
):

    for value in fact.get(
        "structured_values",
        [],
    ):

        if (
            value.get(
                "value_type"
            )
            != "date"
        ):

            continue

        date_value = (
            value.get(
                "date_value"
            )
        )

        if date_value:

            return date_value

    return None


def iso_date_to_tr(
    value,
):

    if not value:

        return None

    try:

        parsed = datetime.strptime(
            value,
            "%Y-%m-%d",
        )

    except ValueError:

        return value

    return parsed.strftime(
        "%d.%m.%Y"
    )


def extract_tr_date_from_text(
    text,
):

    if not text:

        return None

    match = re.search(
        r"\b"
        r"([0-3]?\d)"
        r"\."
        r"([01]?\d)"
        r"\."
        r"(\d{4})"
        r"\b",
        str(text),
    )

    if not match:

        return None

    day = int(
        match.group(1)
    )

    month = int(
        match.group(2)
    )

    year = int(
        match.group(3)
    )

    try:

        parsed = datetime(
            year,
            month,
            day,
        )

    except ValueError:

        return None

    return parsed.strftime(
        "%d.%m.%Y"
    )


# ============================================================
# EVIDENTIARY OVERCLAIM GUARD - V1.3
# ============================================================

def apply_evidentiary_overclaim_guard(
    fact,
    context,
):

    actions = []

    if not is_pleading_document(
        context
    ):

        return actions

    source = fact.get(
        "source",
        {},
    )

    if not isinstance(
        source,
        dict,
    ):

        source = {}

    section = str(
        source.get(
            "section"
        )
        or ""
    )

    excerpt = str(
        source.get(
            "text_excerpt"
        )
        or ""
    )

    statement = str(
        fact.get(
            "statement"
        )
        or ""
    )

    section_normalized = (
        section.casefold()
    )

    excerpt_normalized = (
        excerpt.casefold()
    )

    statement_normalized = (
        statement.casefold()
    )

    # ========================================================
    # GUARD 1:
    #
    # "Dava Tarihi: 05.03.2026"
    #
    # yalnızca bir date fact'tir.
    #
    # "mahkemeye sunuldu"
    # "dava açıldı"
    #
    # gibi ek bir usuli olay üretilemez.
    # ========================================================

    is_dava_tarihi_source = (
        "dava tarihi"
        in section_normalized
        or bool(
            re.search(
                r"\bdava\s+tarihi\s*:",
                excerpt_normalized,
            )
        )
    )

    if is_dava_tarihi_source:

        source_has_filing_assertion = any(
            phrase
            in excerpt_normalized
            for phrase
            in FILING_ASSERTION_PHRASES
        )

        statement_has_filing_assertion = any(
            phrase
            in statement_normalized
            for phrase
            in FILING_ASSERTION_PHRASES
        )

        # ----------------------------------------------------
        # Dava Tarihi label'ını canonical date_fact yap.
        # ----------------------------------------------------

        date_value = (
            get_first_structured_date(
                fact
            )
        )

        display_date = (
            iso_date_to_tr(
                date_value
            )
        )

        if not display_date:

            display_date = (
                extract_tr_date_from_text(
                    excerpt
                )
            )

        if display_date:

            canonical_statement = (
                "Dava dilekçesinde dava tarihi "
                f"{display_date} olarak belirtilmiştir."
            )

            if (
                fact.get(
                    "fact_kind"
                )
                != "date_fact"
            ):

                actions.append(
                    {
                        "type":
                            "fact_kind_normalized",

                        "from":
                            fact.get(
                                "fact_kind"
                            ),

                        "to":
                            "date_fact",
                    }
                )

                fact[
                    "fact_kind"
                ] = "date_fact"

            if (
                statement_has_filing_assertion
                and not source_has_filing_assertion
            ):

                actions.append(
                    {
                        "type":
                            "unsupported_procedural_assertion_removed",

                        "from":
                            statement,

                        "to":
                            canonical_statement,
                    }
                )

                fact[
                    "statement"
                ] = (
                    canonical_statement
                )

                fact[
                    "notes"
                ] = append_note(
                    fact.get(
                        "notes"
                    ),
                    (
                        "Kaynak yalnızca dava tarihini "
                        "belirtmektedir; mahkemeye sunulma, "
                        "tevdi veya dava açılma tarihi "
                        "bu fact ile doğrulanmamıştır."
                    ),
                )

            # ------------------------------------------------
            # Statement filing assertion içermese bile
            # "Dava Tarihi" alanını canonical dile getir.
            # ------------------------------------------------

            elif (
                "dava tarihi"
                not in statement_normalized
                or "belirtilmiştir"
                not in statement_normalized
            ):

                actions.append(
                    {
                        "type":
                            "date_statement_normalized",

                        "from":
                            statement,

                        "to":
                            canonical_statement,
                    }
                )

                fact[
                    "statement"
                ] = (
                    canonical_statement
                )

    return actions


# ============================================================
# DOCUMENT REFERENCE RESOLUTION
# ============================================================

def resolve_document_references(
    facts,
    case_id,
    source_document_id,
):

    resolver = (
        DocumentReferenceResolver(
            case_id=case_id
        )
    )

    resolution_records = []

    warnings = []

    for fact in facts:

        resolution = (
            resolver.apply_to_fact(
                fact,
                source_document_id=
                    source_document_id,
            )
        )

        if resolution[
            "resolved"
        ]:

            resolution_records.append(
                {
                    "fact_id":
                        fact.get(
                            "fact_id"
                        ),

                    "resolved":
                        resolution[
                            "resolved"
                        ],
                }
            )

            for resolved in resolution[
                "resolved"
            ]:

                if not resolved.get(
                    "relation_supported"
                ):

                    warning = (
                        "Document reference resolver: "
                        f"{fact.get('fact_id')} içinde "
                        f"{resolved.get('reference_value')} "
                        "reference-number ile çözüldü ancak "
                        "document relation desteği bulunamadı."
                    )

                    if warning not in warnings:

                        warnings.append(
                            warning
                        )

    return (
        resolution_records,
        warnings,
    )


# ============================================================
# BUILD EXTRACTION
# ============================================================

def build_extraction(
    raw_result,
    case_id,
    document_id,
    context,
    model,
):

    run_stamp = (
        datetime.now()
        .strftime(
            "%Y%m%d_%H%M%S"
        )
    )

    extraction_id = (
        f"extract_{document_id}_"
        f"llm_v1_3_{run_stamp}"
    )

    raw_facts = (
        raw_result.get(
            "facts",
            [],
        )
    )

    if not isinstance(
        raw_facts,
        list,
    ):

        raw_facts = []

    facts = []

    filtered_meta_count = 0

    semantic_guard_records = []

    for raw_fact in raw_facts:

        if is_meta_test_fact(
            raw_fact
        ):

            filtered_meta_count += 1

            continue

        next_index = (
            len(facts)
            + 1
        )

        fact_id = (
            f"fact_{document_id}_"
            f"llm_v1_3_{run_stamp}_"
            f"{next_index:03d}"
        )

        normalized = normalize_fact(
            raw_fact,
            fact_id,
            context,
        )

        if normalized is None:

            continue

        # ====================================================
        # V1.3 SEMANTIC SAFETY
        # ====================================================

        guard_actions = (
            apply_evidentiary_overclaim_guard(
                normalized,
                context,
            )
        )

        if guard_actions:

            semantic_guard_records.append(
                {
                    "fact_id":
                        fact_id,

                    "actions":
                        guard_actions,
                }
            )

        facts.append(
            normalized
        )

    # ========================================================
    # DOCUMENT REFERENCE RESOLVER
    # ========================================================

    (
        resolution_records,
        resolver_warnings,
    ) = resolve_document_references(
        facts=facts,
        case_id=case_id,
        source_document_id=document_id,
    )

    # ========================================================
    # WARNING HYGIENE
    # ========================================================

    warnings = normalize_llm_warnings(
        raw_result.get(
            "warnings",
            [],
        )
    )

    for warning in resolver_warnings:

        if warning not in warnings:

            warnings.append(
                warning
            )

    # ========================================================
    # STATUS
    # ========================================================

    status = (
        "completed"
        if facts
        else "failed"
    )

    extraction = {
        "schema_version":
            1,

        "extraction_id":
            extraction_id,

        "case_id":
            case_id,

        "source_document_id":
            document_id,

        "status":
            status,

        "extractor": {
            "method":
                "llm",

            "provider":
                "anthropic",

            "model":
                model,

            "extractor_version":
                FACT_EXTRACTION_ENGINE_VERSION,

            "prompt_version":
                PROMPT_VERSION,

            "run_at":
                datetime.now()
                .astimezone()
                .isoformat(),
        },

        "facts":
            facts,

        "warnings":
            warnings,

        "notes":
            (
                "Fact Extraction Engine V1.3 "
                "tarafından üretilmiş pending "
                "LLM extraction çıktısıdır. "
                "Pleading belgelerde source attribution "
                "deterministik olarak document issuer'a "
                "kilitlenmiştir. Evidentiary Overclaim Guard "
                "desteklenmeyen usuli çıkarımları sınırlar. "
                "related_document_ids alanları Document "
                "Reference Resolver V1 tarafından "
                "deterministik olarak oluşturulmuştur. "
                "İnsan onayı olmadan canonical değildir."
            ),

        # ----------------------------------------------------
        # Runtime only.
        # Schema'ya yazılmayacak.
        # ----------------------------------------------------

        "_runtime_document_resolutions":
            resolution_records,

        "_runtime_filtered_meta_count":
            filtered_meta_count,

        "_runtime_semantic_guard_records":
            semantic_guard_records,
    }

    return extraction


# ============================================================
# REMOVE RUNTIME FIELDS
# ============================================================

def prepare_for_schema(
    extraction,
):

    runtime_resolutions = (
        extraction.pop(
            "_runtime_document_resolutions",
            [],
        )
    )

    filtered_meta_count = (
        extraction.pop(
            "_runtime_filtered_meta_count",
            0,
        )
    )

    semantic_guard_records = (
        extraction.pop(
            "_runtime_semantic_guard_records",
            [],
        )
    )

    return {
        "document_resolutions":
            runtime_resolutions,

        "filtered_meta_count":
            filtered_meta_count,

        "semantic_guard_records":
            semantic_guard_records,
    }


# ============================================================
# ENGINE
# ============================================================

def run_fact_extraction(
    case_id,
    document_id,
    text_path,
    model=DEFAULT_MODEL,
):

    (
        case_data,
        document_data,
        case_dir,
    ) = load_case_context(
        case_id,
        document_id,
    )

    document_text = load_text(
        text_path
    )

    context = build_allowed_context(
        case_data,
        document_data,
    )

    prompt = build_user_prompt(
        context,
        document_text,
    )

    print()

    print(
        "LLM fact extraction başlatılıyor..."
    )

    print(
        "Engine:",
        FACT_EXTRACTION_ENGINE_VERSION,
    )

    print(
        "Prompt:",
        PROMPT_VERSION,
    )

    print(
        "Model:",
        model,
    )

    print(
        "Belge:",
        document_id,
    )

    print(
        "Belge türü:",
        context.get(
            "source_document_type"
        ),
    )

    print(
        "Source actor:",
        (
            context.get(
                "source_actor_label"
            )
            or "Bilinmiyor"
        ),
    )

    print(
        "Source attribution lock:",
        (
            "ON"
            if is_pleading_document(
                context
            )
            else "OFF"
        ),
    )

    print(
        "Karakter:",
        len(
            document_text
        ),
    )

    # ========================================================
    # LLM
    # ========================================================

    raw_text = call_llm(
        prompt,
        model,
    )

    raw_result = parse_llm_json(
        raw_text
    )

    # ========================================================
    # NORMALIZE + SAFETY + RESOLVE
    # ========================================================

    extraction = build_extraction(
        raw_result,
        case_id,
        document_id,
        context,
        model,
    )

    runtime = prepare_for_schema(
        extraction
    )

    # ========================================================
    # OUTPUT
    # ========================================================

    output_path = (
        case_dir
        / "documents"
        / document_id
        / "extractions"
        / "facts_llm_v1_3.json.pending"
    )

    write_json(
        output_path,
        extraction,
    )

    # ========================================================
    # FINAL VALIDATION
    # ========================================================

    validation = (
        validate_fact_extraction(
            facts_path=output_path,
            raise_on_error=True,
        )
    )

    return {
        "output_path":
            output_path,

        "extraction":
            extraction,

        "validation":
            validation,

        "document_resolutions":
            runtime[
                "document_resolutions"
            ],

        "filtered_meta_count":
            runtime[
                "filtered_meta_count"
            ],

        "semantic_guard_records":
            runtime[
                "semantic_guard_records"
            ],
    }


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Vergi AI Fact Extraction Engine V1.3"
        )
    )

    parser.add_argument(
        "--case",
        default=DEFAULT_CASE_ID,
        dest="case_id",
    )

    parser.add_argument(
        "--document",
        default=DEFAULT_DOCUMENT_ID,
        dest="document_id",
    )

    parser.add_argument(
        "--text-file",
        default=str(
            DEFAULT_TEXT_PATH
        ),
        dest="text_path",
    )

    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
    )

    args = parser.parse_args()

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - FACT EXTRACTION ENGINE V1.3"
    )

    print(
        "======================================"
    )

    result = run_fact_extraction(
        case_id=args.case_id,
        document_id=args.document_id,
        text_path=Path(
            args.text_path
        ),
        model=args.model,
    )

    extraction = result[
        "extraction"
    ]

    validation = result[
        "validation"
    ]

    resolutions = result[
        "document_resolutions"
    ]

    semantic_guard_records = (
        result[
            "semantic_guard_records"
        ]
    )

    print()

    print(
        "FACT EXTRACTION TAMAMLANDI"
    )

    print(
        "Extraction ID:",
        extraction[
            "extraction_id"
        ],
    )

    print(
        "Fact sayısı:",
        len(
            extraction[
                "facts"
            ]
        ),
    )

    print(
        "Status:",
        extraction[
            "status"
        ],
    )

    print(
        "Validator:",
        (
            "PASS"
            if validation[
                "valid"
            ]
            else "FAIL"
        ),
    )

    # ========================================================
    # DOCUMENT RESOLVER
    # ========================================================

    print()

    print(
        "Document resolver:"
    )

    if resolutions:

        for record in resolutions:

            fact_id = (
                record[
                    "fact_id"
                ]
            )

            for resolved in record[
                "resolved"
            ]:

                print(
                    "-",
                    fact_id,
                    ":",
                    resolved[
                        "reference_value"
                    ],
                    "->",
                    resolved[
                        "document_id"
                    ],
                    "| relation_supported=",
                    resolved[
                        "relation_supported"
                    ],
                )

    else:

        print(
            "- Çözümlenen document reference yok."
        )

    # ========================================================
    # SEMANTIC SAFETY GUARD
    # ========================================================

    print()

    print(
        "Semantic safety guard:"
    )

    if semantic_guard_records:

        for record in semantic_guard_records:

            print(
                "-",
                record[
                    "fact_id"
                ],
            )

            for action in record[
                "actions"
            ]:

                print(
                    "  ",
                    action[
                        "type"
                    ],
                    ":",
                    action.get(
                        "from"
                    ),
                    "->",
                    action.get(
                        "to"
                    ),
                )

    else:

        print(
            "- Deterministic semantic correction gerekmedi."
        )

    # ========================================================
    # META FILTER
    # ========================================================

    if result[
        "filtered_meta_count"
    ]:

        print()

        print(
            "Meta filter:"
        )

        print(
            "-",
            result[
                "filtered_meta_count"
            ],
            "adet test/demo/development fact "
            "case fact listesinden çıkarıldı."
        )

    # ========================================================
    # OUTPUT
    # ========================================================

    print()

    print(
        "Pending output:"
    )

    print(
        result[
            "output_path"
        ]
    )

    # ========================================================
    # CASE WARNINGS
    # ========================================================

    if extraction.get(
        "warnings"
    ):

        print()

        print(
            "Case warnings:"
        )

        for warning in extraction[
            "warnings"
        ]:

            print(
                "-",
                warning,
            )

    else:

        print()

        print(
            "Case warning yok."
        )

    print()

    print(
        "NOT:"
    )

    print(
        "Pleading belgelerde attributed_party_id ve "
        "attributed_actor_label source document issuer "
        "üzerinden deterministik olarak kilitlenir."
    )

    print()

    print(
        "Kaynak metnin desteklemediği mahkemeye sunulma, "
        "dava açılma veya tevdi gibi usuli çıkarımlar "
        "Evidentiary Overclaim Guard tarafından sınırlandırılır."
    )

    print()

    print(
        "related_document_ids değerleri LLM tarafından "
        "değil Document Reference Resolver V1 tarafından "
        "belirlenir."
    )

    print()

    print(
        "Bu extraction henüz "
        "Fact Repository'ye alınmadı."
    )

    print()

    print(
        "======================================"
    )

    print(
        " FACT EXTRACTION ENGINE V1.3: PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    main()