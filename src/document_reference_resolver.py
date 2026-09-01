# ============================================================
# VERGİ AI - DOCUMENT REFERENCE RESOLVER V1
#
# AMAÇ:
#
# Fact extraction içindeki belge atıflarını
# deterministik olarak case document_id değerlerine çözmek.
#
#
# ÖRNEK:
#
# Fact:
#   "VIR-DEMO-2026-001 sayılı Vergi İnceleme Raporu..."
#
#                 ↓
#
# structured_value:
#   reference_value = "VIR-DEMO-2026-001"
#
#                 ↓
#
# CASE DOCUMENT METADATA
#
# vir_001/document.json
#   reference_numbers:
#       value = "VIR-DEMO-2026-001"
#
#                 ↓
#
# related_document_ids = ["vir_001"]
#
#
# KRİTİK PRENSİPLER:
#
# 1. LLM document_id seçmez.
#
# 2. Resolver yalnızca case metadata üzerinden karar verir.
#
# 3. Exact reference-number match temel sinyaldir.
#
# 4. Document relations ek doğrulama sinyalidir.
#
# 5. Ambiguous reference fail-closed olur.
#
# 6. Kaynak belge kendisine related_document olamaz.
#
# 7. Metadata'da relation var diye fact'e otomatik belge
#    bağlanmaz. Fact'in gerçekten o belgeye atıf yapması gerekir.
# ============================================================


import json
import re

from pathlib import Path


# ============================================================
# VERSION
# ============================================================

DOCUMENT_REFERENCE_RESOLVER_VERSION = "1"


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

CASES_DIR = (
    DATA_DIR
    / "cases"
)


# ============================================================
# EXCEPTIONS
# ============================================================

class DocumentReferenceResolverError(
    Exception
):
    pass


class DocumentReferenceAmbiguityError(
    DocumentReferenceResolverError
):
    pass


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


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_reference(
    value,
):

    if value is None:
        return None

    text = str(
        value
    ).strip()

    if not text:
        return None

    # Unicode case-insensitive normalization
    text = text.casefold()

    # Farklı tire karakterlerini normalize et
    text = (
        text
        .replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
    )

    # Gereksiz whitespace kaldır
    text = re.sub(
        r"\s+",
        "",
        text,
    )

    return text


# ============================================================
# REPOSITORY
# ============================================================

class DocumentReferenceResolver:

    def __init__(
        self,
        case_id,
        cases_dir=None,
    ):

        self.case_id = case_id

        if cases_dir is None:
            cases_dir = CASES_DIR

        self.cases_dir = Path(
            cases_dir
        ).resolve()

        self.case_dir = (
            self.cases_dir
            / case_id
        )

        self.documents_dir = (
            self.case_dir
            / "documents"
        )

        if not self.case_dir.exists():

            raise FileNotFoundError(
                "Case bulunamadı:\n"
                f"{self.case_dir}"
            )

        if not self.documents_dir.exists():

            raise FileNotFoundError(
                "Documents klasörü bulunamadı:\n"
                f"{self.documents_dir}"
            )

        self.documents = (
            self._load_documents()
        )

        self.reference_index = (
            self._build_reference_index()
        )


    # ========================================================
    # LOAD DOCUMENTS
    # ========================================================

    def _load_documents(
        self,
    ):

        documents = {}

        for document_path in sorted(
            self.documents_dir.glob(
                "*/document.json"
            )
        ):

            data = load_json(
                document_path
            )

            document_id = data.get(
                "document_id"
            )

            if not document_id:
                continue

            if (
                data.get(
                    "case_id"
                )
                != self.case_id
            ):

                raise (
                    DocumentReferenceResolverError(
                        "Document case_id uyuşmazlığı:\n"
                        f"{document_path}"
                    )
                )

            if document_id in documents:

                raise (
                    DocumentReferenceResolverError(
                        "Duplicate document_id: "
                        f"{document_id}"
                    )
                )

            documents[
                document_id
            ] = {
                "data":
                    data,

                "path":
                    document_path,
            }

        return documents


    # ========================================================
    # REFERENCE INDEX
    # ========================================================

    def _build_reference_index(
        self,
    ):

        index = {}

        for (
            document_id,
            record,
        ) in self.documents.items():

            document = record[
                "data"
            ]

            for reference in document.get(
                "reference_numbers",
                [],
            ):

                value = reference.get(
                    "value"
                )

                normalized = (
                    normalize_reference(
                        value
                    )
                )

                if not normalized:
                    continue

                index.setdefault(
                    normalized,
                    [],
                )

                index[
                    normalized
                ].append(
                    {
                        "document_id":
                            document_id,

                        "reference_type":
                            reference.get(
                                "reference_type"
                            ),

                        "value":
                            value,

                        "issuing_body":
                            reference.get(
                                "issuing_body"
                            ),
                    }
                )

        return index


    # ========================================================
    # RELATION HELPERS
    # ========================================================

    def get_relation_between(
        self,
        source_document_id,
        target_document_id,
    ):

        matches = []

        source_record = (
            self.documents.get(
                source_document_id
            )
        )

        target_record = (
            self.documents.get(
                target_document_id
            )
        )

        if source_record:

            for relation in (
                source_record[
                    "data"
                ].get(
                    "relations",
                    [],
                )
            ):

                if (
                    relation.get(
                        "document_id"
                    )
                    == target_document_id
                ):

                    matches.append(
                        {
                            "direction":
                                "source_to_target",

                            "type":
                                relation.get(
                                    "type"
                                ),
                        }
                    )

        if target_record:

            for relation in (
                target_record[
                    "data"
                ].get(
                    "relations",
                    [],
                )
            ):

                if (
                    relation.get(
                        "document_id"
                    )
                    == source_document_id
                ):

                    matches.append(
                        {
                            "direction":
                                "target_to_source",

                            "type":
                                relation.get(
                                    "type"
                                ),
                        }
                    )

        return matches


    # ========================================================
    # EXACT REFERENCE LOOKUP
    # ========================================================

    def resolve_reference_value(
        self,
        reference_value,
        source_document_id=None,
    ):

        normalized = (
            normalize_reference(
                reference_value
            )
        )

        if not normalized:

            return None

        matches = list(
            self.reference_index.get(
                normalized,
                [],
            )
        )

        # ----------------------------------------------------
        # Source document kendisine bağlanamaz.
        # ----------------------------------------------------

        if source_document_id:

            matches = [
                match
                for match in matches
                if match[
                    "document_id"
                ]
                != source_document_id
            ]

        if not matches:

            return None

        # ----------------------------------------------------
        # Exact reference birden fazla document'a aitse
        # fail closed.
        # ----------------------------------------------------

        unique_document_ids = {
            match[
                "document_id"
            ]
            for match in matches
        }

        if len(
            unique_document_ids
        ) > 1:

            raise (
                DocumentReferenceAmbiguityError(
                    "Reference birden fazla case "
                    "document ile eşleşiyor: "
                    f"{reference_value} -> "
                    f"{sorted(unique_document_ids)}"
                )
            )

        match = matches[
            0
        ]

        document_id = match[
            "document_id"
        ]

        relations = []

        if source_document_id:

            relations = (
                self.get_relation_between(
                    source_document_id,
                    document_id,
                )
            )

        return {
            "document_id":
                document_id,

            "match_type":
                "exact_reference_number",

            "reference_value":
                match[
                    "value"
                ],

            "reference_type":
                match[
                    "reference_type"
                ],

            "issuing_body":
                match[
                    "issuing_body"
                ],

            "relations":
                relations,

            "relation_supported":
                bool(
                    relations
                ),
        }


    # ========================================================
    # STRUCTURED REFERENCE VALUES
    # ========================================================

    @staticmethod
    def extract_structured_references(
        fact,
    ):

        values = []

        for structured in fact.get(
            "structured_values",
            [],
        ):

            if (
                structured.get(
                    "value_type"
                )
                != "reference"
            ):
                continue

            reference_value = (
                structured.get(
                    "reference_value"
                )
            )

            if (
                reference_value
                and reference_value
                not in values
            ):

                values.append(
                    reference_value
                )

        return values


    # ========================================================
    # TEXT REFERENCE VALUES
    # ========================================================

    def extract_known_references_from_text(
        self,
        fact,
        source_document_id=None,
    ):

        source = fact.get(
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
                    fact.get(
                        "statement",
                        ""
                    )
                ),
                str(
                    source.get(
                        "text_excerpt",
                        ""
                    )
                ),
            ]
        )

        combined_normalized = (
            normalize_reference(
                combined
            )
            or ""
        )

        found = []

        for (
            normalized_reference,
            matches,
        ) in self.reference_index.items():

            if (
                normalized_reference
                not in combined_normalized
            ):
                continue

            for match in matches:

                document_id = (
                    match[
                        "document_id"
                    ]
                )

                if (
                    source_document_id
                    and document_id
                    == source_document_id
                ):
                    continue

                value = match[
                    "value"
                ]

                if value not in found:

                    found.append(
                        value
                    )

        return found


    # ========================================================
    # RESOLVE FACT
    # ========================================================

    def resolve_fact(
        self,
        fact,
        source_document_id,
    ):

        candidate_references = []

        # ----------------------------------------------------
        # 1. Structured references
        # ----------------------------------------------------

        for reference in (
            self.extract_structured_references(
                fact
            )
        ):

            if (
                reference
                not in candidate_references
            ):

                candidate_references.append(
                    reference
                )

        # ----------------------------------------------------
        # 2. Known refs visibly appearing in fact text
        # ----------------------------------------------------

        for reference in (
            self.extract_known_references_from_text(
                fact,
                source_document_id=
                    source_document_id,
            )
        ):

            if (
                reference
                not in candidate_references
            ):

                candidate_references.append(
                    reference
                )

        resolved = []

        unresolved = []

        seen_document_ids = set()

        for reference in candidate_references:

            match = (
                self.resolve_reference_value(
                    reference,
                    source_document_id=
                        source_document_id,
                )
            )

            if match is None:

                unresolved.append(
                    reference
                )

                continue

            document_id = match[
                "document_id"
            ]

            if (
                document_id
                in seen_document_ids
            ):

                continue

            seen_document_ids.add(
                document_id
            )

            resolved.append(
                match
            )

        return {
            "related_document_ids":
                [
                    item[
                        "document_id"
                    ]
                    for item
                    in resolved
                ],

            "resolved":
                resolved,

            "unresolved":
                unresolved,
        }


    # ========================================================
    # APPLY TO FACT
    # ========================================================

    def apply_to_fact(
        self,
        fact,
        source_document_id,
    ):

        resolution = (
            self.resolve_fact(
                fact,
                source_document_id,
            )
        )

        # ----------------------------------------------------
        # LLM'in verdiği related_document_ids dikkate alınmaz.
        #
        # Resolver sonucu overwrite eder.
        # ----------------------------------------------------

        fact[
            "related_document_ids"
        ] = resolution[
            "related_document_ids"
        ]

        return resolution


# ============================================================
# BASIC TESTS
# ============================================================

def run_basic_tests():

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - DOCUMENT REFERENCE RESOLVER V1"
    )

    print(
        "======================================"
    )

    resolver = (
        DocumentReferenceResolver(
            case_id="case_0001"
        )
    )


    # ========================================================
    # T01 - DOCUMENT LOAD
    # ========================================================

    assert (
        "vir_001"
        in resolver.documents
    )

    assert (
        "ihbarname_001"
        in resolver.documents
    )

    print(
        "T01 Document load:",
        "PASS"
    )


    # ========================================================
    # T02 - EXACT REFERENCE
    # ========================================================

    result = (
        resolver.resolve_reference_value(
            "VIR-DEMO-2026-001",
            source_document_id=
                "ihbarname_001",
        )
    )

    assert result is not None

    assert (
        result[
            "document_id"
        ]
        == "vir_001"
    )

    print(
        "T02 Exact reference:",
        "PASS"
    )


    # ========================================================
    # T03 - RELATION SUPPORT
    # ========================================================

    assert (
        result[
            "relation_supported"
        ]
        is True
    )

    relation_types = {
        relation[
            "type"
        ]
        for relation
        in result[
            "relations"
        ]
    }

    assert (
        "refers_to"
        in relation_types
        or "basis_for"
        in relation_types
    )

    print(
        "T03 Relation support:",
        "PASS"
    )


    # ========================================================
    # T04 - SELF REFERENCE BLOCK
    # ========================================================

    self_result = (
        resolver.resolve_reference_value(
            "VIR-DEMO-2026-001",
            source_document_id=
                "vir_001",
        )
    )

    assert (
        self_result
        is None
    )

    print(
        "T04 Self-reference block:",
        "PASS"
    )


    # ========================================================
    # T05 - UNKNOWN REFERENCE
    # ========================================================

    unknown = (
        resolver.resolve_reference_value(
            "UNKNOWN-999",
            source_document_id=
                "ihbarname_001",
        )
    )

    assert (
        unknown
        is None
    )

    print(
        "T05 Unknown reference:",
        "PASS"
    )


    # ========================================================
    # T06 - FACT RESOLUTION
    # ========================================================

    fact = {
        "statement":
            (
                "İhbarname VIR-DEMO-2026-001 "
                "sayılı Vergi İnceleme Raporuna "
                "dayanmaktadır."
            ),

        "source": {
            "text_excerpt":
                (
                    "VIR-DEMO-2026-001 sayılı "
                    "Vergi İnceleme Raporu"
                )
        },

        "structured_values": [
            {
                "value_type":
                    "reference",

                "reference_value":
                    "VIR-DEMO-2026-001",
            }
        ],

        # Bilerek yanlış:
        "related_document_ids": [
            "dava_dilekcesi_001"
        ],
    }

    resolution = (
        resolver.apply_to_fact(
            fact,
            source_document_id=
                "ihbarname_001",
        )
    )

    assert (
        fact[
            "related_document_ids"
        ]
        == [
            "vir_001"
        ]
    )

    assert (
        resolution[
            "related_document_ids"
        ]
        == [
            "vir_001"
        ]
    )

    print(
        "T06 Deterministic overwrite:",
        "PASS"
    )


    # ========================================================
    # T07 - TEXT-ONLY REFERENCE
    # ========================================================

    text_only_fact = {
        "statement":
            (
                "VIR-DEMO-2026-001 sayılı "
                "rapordaki tespitler esas alınmıştır."
            ),

        "source": {
            "text_excerpt":
                None
        },

        "structured_values":
            [],

        "related_document_ids":
            [],
    }

    text_resolution = (
        resolver.resolve_fact(
            text_only_fact,
            source_document_id=
                "ihbarname_001",
        )
    )

    assert (
        text_resolution[
            "related_document_ids"
        ]
        == [
            "vir_001"
        ]
    )

    print(
        "T07 Text-only reference:",
        "PASS"
    )


    # ========================================================
    # T08 - SOURCE DOCUMENT OWN NUMBER
    # ========================================================

    own_result = (
        resolver.resolve_reference_value(
            "IHB-DEMO-2026-001",
            source_document_id=
                "ihbarname_001",
        )
    )

    assert (
        own_result
        is None
    )

    print(
        "T08 Own document number isolation:",
        "PASS"
    )


    print()

    print(
        "Resolved:"
    )

    print(
        "VIR-DEMO-2026-001"
        " -> "
        f"{result['document_id']}"
    )

    print(
        "Relation supported:",
        result[
            "relation_supported"
        ]
    )

    print(
        "Relations:",
        result[
            "relations"
        ]
    )

    print()

    print(
        "======================================"
    )

    print(
        " DOCUMENT REFERENCE RESOLVER V1: 8/8 PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    run_basic_tests()