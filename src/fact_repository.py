# ============================================================
# VERGİ AI - FACT REPOSITORY V1.1
#
# AMAÇ:
#
# Case içindeki ONAYLANMIŞ / CANONICAL fact extraction
# kayıtlarını merkezi olarak yüklemek ve sorgulamak.
#
#
# V1.1 DEĞİŞİKLİKLER:
#
# 1. Yalnızca:
#
#       */extractions/facts.json
#
#    canonical kayıtlarını okur.
#
# 2. *.pending dosyalarını ASLA repository'ye almaz.
#
# 3. history/ ve reviews/ kayıtlarını repository'ye almaz.
#
# 4. Hard-coded fact sayısı testleri kaldırıldı.
#
# 5. Testler canonical içeriğe göre dinamik hale getirildi.
#
#
# KRİTİK PRENSİP:
#
# LLM OUTPUT
#     ↓
# pending
#     ↓
# validator
#     ↓
# human approval
#     ↓
# facts.json
#     ↓
# FACT REPOSITORY
#
#
# Repository:
#   kayıt / erişim katmanıdır.
#
# Repository:
#   hukuki değerlendirme üretmez.
# ============================================================


import copy
import json

from pathlib import Path

from case_fact_validator import (
    validate_fact_extraction,
)


# ============================================================
# VERSION
# ============================================================

FACT_REPOSITORY_VERSION = "1.1"


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

class FactRepositoryError(Exception):
    pass


class CaseNotFoundError(
    FactRepositoryError
):
    pass


class DuplicateExtractionIDError(
    FactRepositoryError
):
    pass


class DuplicateFactIDError(
    FactRepositoryError
):
    pass


class FactNotFoundError(
    FactRepositoryError
):
    pass


class AmbiguousFactError(
    FactRepositoryError
):
    pass


class InvalidCanonicalExtractionError(
    FactRepositoryError
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
# REPOSITORY
# ============================================================

class FactRepository:

    def __init__(
        self,
        cases_dir=None,
        validate=True,
    ):

        if cases_dir is None:
            cases_dir = CASES_DIR

        self.cases_dir = Path(
            cases_dir
        ).resolve()

        self.validate = validate


    # ========================================================
    # CASE DIR
    # ========================================================

    def get_case_dir(
        self,
        case_id,
    ):

        case_dir = (
            self.cases_dir
            / case_id
        )

        if not case_dir.exists():

            raise CaseNotFoundError(
                "Case bulunamadı: "
                f"{case_id}\n"
                f"{case_dir}"
            )

        case_path = (
            case_dir
            / "case.json"
        )

        if not case_path.exists():

            raise CaseNotFoundError(
                "Case klasörü bulundu ancak "
                "case.json yok:\n"
                f"{case_path}"
            )

        return case_dir


    # ========================================================
    # CANONICAL EXTRACTION DISCOVERY
    # ========================================================

    def discover_extraction_files(
        self,
        case_id,
    ):

        case_dir = self.get_case_dir(
            case_id
        )

        documents_dir = (
            case_dir
            / "documents"
        )

        if not documents_dir.exists():

            return []

        # ----------------------------------------------------
        # V1.1:
        #
        # Sadece canonical:
        #
        # documents/<id>/extractions/facts.json
        #
        # Pending / history / reviews okunmaz.
        # ----------------------------------------------------

        extraction_files = sorted(
            documents_dir.glob(
                "*/extractions/facts.json"
            )
        )

        return extraction_files


    # ========================================================
    # LOAD CANONICAL EXTRACTION
    # ========================================================

    def load_extraction(
        self,
        extraction_path,
    ):

        extraction_path = Path(
            extraction_path
        ).resolve()

        if (
            extraction_path.name
            != "facts.json"
        ):

            raise InvalidCanonicalExtractionError(
                "Repository yalnızca canonical "
                "facts.json kabul eder:\n"
                f"{extraction_path}"
            )

        if self.validate:

            validate_fact_extraction(
                facts_path=extraction_path,
                raise_on_error=True,
            )

        extraction = load_json(
            extraction_path
        )

        if (
            extraction.get(
                "status"
            )
            != "completed"
        ):

            raise InvalidCanonicalExtractionError(
                "Canonical extraction status=completed "
                "olmalıdır:\n"
                f"{extraction_path}"
            )

        if not extraction.get(
            "facts"
        ):

            raise InvalidCanonicalExtractionError(
                "Canonical extraction fact içermiyor:\n"
                f"{extraction_path}"
            )

        return extraction


    # ========================================================
    # EXTRACTIONS
    # ========================================================

    def get_extractions(
        self,
        case_id,
    ):

        files = (
            self.discover_extraction_files(
                case_id
            )
        )

        results = []

        seen_extraction_ids = {}

        for path in files:

            extraction = (
                self.load_extraction(
                    path
                )
            )

            extraction_id = (
                extraction.get(
                    "extraction_id"
                )
            )

            if extraction_id in seen_extraction_ids:

                raise DuplicateExtractionIDError(
                    "Case içinde tekrarlanan "
                    "extraction_id bulundu: "
                    f"{extraction_id}\n"
                    "İlk: "
                    f"{seen_extraction_ids[extraction_id]}\n"
                    "İkinci: "
                    f"{path}"
                )

            seen_extraction_ids[
                extraction_id
            ] = str(
                path
            )

            results.append(
                {
                    "extraction_id":
                        extraction_id,

                    "case_id":
                        extraction.get(
                            "case_id"
                        ),

                    "source_document_id":
                        extraction.get(
                            "source_document_id"
                        ),

                    "status":
                        extraction.get(
                            "status"
                        ),

                    "extractor":
                        copy.deepcopy(
                            extraction.get(
                                "extractor"
                            )
                        ),

                    "fact_count":
                        len(
                            extraction.get(
                                "facts",
                                [],
                            )
                        ),

                    "source_path":
                        str(
                            path
                        ),

                    "data":
                        copy.deepcopy(
                            extraction
                        ),
                }
            )

        return results


    # ========================================================
    # BUILD FACT RECORD
    # ========================================================

    def _build_fact_record(
        self,
        extraction,
        extraction_path,
        fact,
    ):

        return {
            "fact":
                copy.deepcopy(
                    fact
                ),

            "fact_id":
                fact.get(
                    "fact_id"
                ),

            "case_id":
                extraction.get(
                    "case_id"
                ),

            "source_document_id":
                extraction.get(
                    "source_document_id"
                ),

            "extraction_id":
                extraction.get(
                    "extraction_id"
                ),

            "extraction_status":
                extraction.get(
                    "status"
                ),

            "extractor":
                copy.deepcopy(
                    extraction.get(
                        "extractor"
                    )
                ),

            "source_path":
                str(
                    extraction_path
                ),
        }


    # ========================================================
    # ALL FACTS
    # ========================================================

    def get_all_facts(
        self,
        case_id,
    ):

        extraction_files = (
            self.discover_extraction_files(
                case_id
            )
        )

        records = []

        seen_fact_ids = {}

        for path in extraction_files:

            extraction = (
                self.load_extraction(
                    path
                )
            )

            for fact in extraction.get(
                "facts",
                [],
            ):

                fact_id = fact.get(
                    "fact_id"
                )

                if fact_id in seen_fact_ids:

                    raise DuplicateFactIDError(
                        "Case çapında tekrarlanan "
                        "fact_id bulundu: "
                        f"{fact_id}\n"
                        "İlk kayıt: "
                        f"{seen_fact_ids[fact_id]}\n"
                        "İkinci kayıt: "
                        f"{path}"
                    )

                seen_fact_ids[
                    fact_id
                ] = str(
                    path
                )

                records.append(
                    self._build_fact_record(
                        extraction,
                        path,
                        fact,
                    )
                )

        return records


    # ========================================================
    # GET FACT
    # ========================================================

    def get_fact(
        self,
        case_id,
        fact_id,
    ):

        matches = [
            record
            for record
            in self.get_all_facts(
                case_id
            )
            if record.get(
                "fact_id"
            ) == fact_id
        ]

        if not matches:

            raise FactNotFoundError(
                "Fact bulunamadı: "
                f"{fact_id}"
            )

        if len(
            matches
        ) > 1:

            raise AmbiguousFactError(
                "Fact ID birden fazla "
                "kayıt döndürdü: "
                f"{fact_id}"
            )

        return matches[
            0
        ]


    # ========================================================
    # FILTER HELPER
    # ========================================================

    @staticmethod
    def _contains(
        values,
        target,
    ):

        if target is None:

            return True

        return target in (
            values
            or []
        )


    # ========================================================
    # FIND FACTS
    # ========================================================

    def find_facts(
        self,
        case_id,
        source_document_id=None,
        fact_kind=None,
        attributed_party_id=None,
        related_party_id=None,
        dispute_item_id=None,
        related_document_id=None,
        verification_state=None,
        min_confidence=None,
        extraction_status=None,
    ):

        records = self.get_all_facts(
            case_id
        )

        results = []

        for record in records:

            fact = record[
                "fact"
            ]

            # =================================================
            # SOURCE DOCUMENT
            # =================================================

            if (
                source_document_id
                is not None
                and record.get(
                    "source_document_id"
                )
                != source_document_id
            ):

                continue

            # =================================================
            # FACT KIND
            # =================================================

            if (
                fact_kind
                is not None
                and fact.get(
                    "fact_kind"
                )
                != fact_kind
            ):

                continue

            # =================================================
            # ATTRIBUTED PARTY
            # =================================================

            if (
                attributed_party_id
                is not None
                and fact.get(
                    "attributed_party_id"
                )
                != attributed_party_id
            ):

                continue

            # =================================================
            # RELATED PARTY
            # =================================================

            if not self._contains(
                fact.get(
                    "related_party_ids"
                ),
                related_party_id,
            ):

                continue

            # =================================================
            # DISPUTE ITEM
            # =================================================

            if not self._contains(
                fact.get(
                    "related_dispute_item_ids"
                ),
                dispute_item_id,
            ):

                continue

            # =================================================
            # RELATED DOCUMENT
            # =================================================

            if not self._contains(
                fact.get(
                    "related_document_ids"
                ),
                related_document_id,
            ):

                continue

            # =================================================
            # VERIFICATION
            # =================================================

            if (
                verification_state
                is not None
                and fact.get(
                    "verification_state"
                )
                != verification_state
            ):

                continue

            # =================================================
            # CONFIDENCE
            # =================================================

            if (
                min_confidence
                is not None
            ):

                confidence = fact.get(
                    "confidence"
                )

                if (
                    confidence is None
                    or confidence
                    < min_confidence
                ):

                    continue

            # =================================================
            # EXTRACTION STATUS
            # =================================================

            if (
                extraction_status
                is not None
                and record.get(
                    "extraction_status"
                )
                != extraction_status
            ):

                continue

            results.append(
                record
            )

        return results


    # ========================================================
    # FIND BY KIND
    # ========================================================

    def find_by_kind(
        self,
        case_id,
        fact_kind,
    ):

        return self.find_facts(
            case_id=case_id,
            fact_kind=fact_kind,
        )


    # ========================================================
    # FIND BY DOCUMENT
    # ========================================================

    def find_by_document(
        self,
        case_id,
        document_id,
    ):

        return self.find_facts(
            case_id=case_id,
            source_document_id=document_id,
        )


    # ========================================================
    # FIND BY DISPUTE ITEM
    # ========================================================

    def find_by_dispute_item(
        self,
        case_id,
        dispute_item_id,
    ):

        return self.find_facts(
            case_id=case_id,
            dispute_item_id=dispute_item_id,
        )


    # ========================================================
    # CASE SUMMARY
    # ========================================================

    def get_case_summary(
        self,
        case_id,
    ):

        facts = self.get_all_facts(
            case_id
        )

        extractions = (
            self.get_extractions(
                case_id
            )
        )

        kinds = {}

        verification_states = {}

        source_documents = set()

        extractor_versions = set()

        for record in facts:

            fact = record[
                "fact"
            ]

            fact_kind = fact.get(
                "fact_kind"
            )

            verification_state = (
                fact.get(
                    "verification_state"
                )
            )

            source_document_id = (
                record.get(
                    "source_document_id"
                )
            )

            extractor = (
                record.get(
                    "extractor"
                )
                or {}
            )

            extractor_version = (
                extractor.get(
                    "extractor_version"
                )
            )

            kinds[
                fact_kind
            ] = (
                kinds.get(
                    fact_kind,
                    0,
                )
                + 1
            )

            verification_states[
                verification_state
            ] = (
                verification_states.get(
                    verification_state,
                    0,
                )
                + 1
            )

            source_documents.add(
                source_document_id
            )

            if extractor_version:

                extractor_versions.add(
                    extractor_version
                )

        return {
            "case_id":
                case_id,

            "repository_version":
                FACT_REPOSITORY_VERSION,

            "extraction_count":
                len(
                    extractions
                ),

            "fact_count":
                len(
                    facts
                ),

            "source_document_count":
                len(
                    source_documents
                ),

            "source_document_ids":
                sorted(
                    source_documents
                ),

            "fact_kinds":
                kinds,

            "verification_states":
                verification_states,

            "extractor_versions":
                sorted(
                    extractor_versions
                ),
        }


# ============================================================
# BASIC TESTS
# ============================================================

def run_basic_tests():

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - FACT REPOSITORY V1.1"
    )

    print(
        "======================================"
    )

    repository = FactRepository(
        validate=True
    )

    case_id = "case_0001"


    # ========================================================
    # T01 - CANONICAL DISCOVERY
    # ========================================================

    extraction_files = (
        repository.discover_extraction_files(
            case_id
        )
    )

    assert extraction_files, (
        "T01 başarısız: "
        "canonical facts.json bulunamadı."
    )

    assert all(
        path.name
        == "facts.json"
        for path
        in extraction_files
    ), (
        "T01 başarısız: "
        "canonical olmayan extraction bulundu."
    )

    print(
        "T01 Canonical discovery:",
        "PASS"
    )


    # ========================================================
    # T02 - PENDING ISOLATION
    # ========================================================

    assert all(
        not str(
            path
        ).endswith(
            ".pending"
        )
        for path
        in extraction_files
    ), (
        "T02 başarısız: "
        "pending extraction repository'ye girdi."
    )

    print(
        "T02 Pending isolation:",
        "PASS"
    )


    # ========================================================
    # T03 - EXTRACTION COUNT / FACT COUNT
    # ========================================================

    extractions = (
        repository.get_extractions(
            case_id
        )
    )

    facts = (
        repository.get_all_facts(
            case_id
        )
    )

    expected_fact_count = sum(
        extraction[
            "fact_count"
        ]
        for extraction
        in extractions
    )

    assert len(
        facts
    ) == expected_fact_count, (
        "T03 başarısız: "
        "repository fact sayısı extraction "
        "toplamıyla eşleşmiyor."
    )

    assert len(
        facts
    ) > 0, (
        "T03 başarısız: "
        "repository fact içermiyor."
    )

    print(
        "T03 Fact count consistency:",
        "PASS"
    )


    # ========================================================
    # T04 - CASE-WIDE UNIQUE FACT IDS
    # ========================================================

    fact_ids = [
        record[
            "fact_id"
        ]
        for record
        in facts
    ]

    assert (
        len(
            fact_ids
        )
        == len(
            set(
                fact_ids
            )
        )
    ), (
        "T04 başarısız: "
        "duplicate fact_id bulundu."
    )

    print(
        "T04 Unique fact IDs:",
        "PASS"
    )


    # ========================================================
    # T05 - GET FACT
    # ========================================================

    sample_record = facts[
        0
    ]

    sample_fact_id = (
        sample_record[
            "fact_id"
        ]
    )

    resolved = (
        repository.get_fact(
            case_id,
            sample_fact_id,
        )
    )

    assert (
        resolved[
            "fact_id"
        ]
        == sample_fact_id
    )

    print(
        "T05 Get fact by ID:",
        "PASS"
    )


    # ========================================================
    # T06 - FACT KIND FILTER
    # ========================================================

    sample_kind = (
        sample_record[
            "fact"
        ][
            "fact_kind"
        ]
    )

    kind_results = (
        repository.find_by_kind(
            case_id,
            sample_kind,
        )
    )

    assert kind_results, (
        "T06 başarısız: "
        "fact_kind filtresi sonuç döndürmedi."
    )

    assert all(
        record[
            "fact"
        ][
            "fact_kind"
        ]
        == sample_kind
        for record
        in kind_results
    )

    print(
        "T06 Fact kind filter:",
        "PASS"
    )


    # ========================================================
    # T07 - DOCUMENT FILTER
    # ========================================================

    sample_document_id = (
        sample_record[
            "source_document_id"
        ]
    )

    document_results = (
        repository.find_by_document(
            case_id,
            sample_document_id,
        )
    )

    expected_document_count = sum(
        extraction[
            "fact_count"
        ]
        for extraction
        in extractions
        if extraction[
            "source_document_id"
        ]
        == sample_document_id
    )

    assert len(
        document_results
    ) == expected_document_count

    assert all(
        record[
            "source_document_id"
        ]
        == sample_document_id
        for record
        in document_results
    )

    print(
        "T07 Document filter:",
        "PASS"
    )


    # ========================================================
    # T08 - DISPUTE ITEM FILTER
    # ========================================================

    sample_dispute_item_id = None

    for record in facts:

        related_ids = (
            record[
                "fact"
            ].get(
                "related_dispute_item_ids",
                [],
            )
        )

        if related_ids:

            sample_dispute_item_id = (
                related_ids[
                    0
                ]
            )

            break

    assert (
        sample_dispute_item_id
        is not None
    ), (
        "T08 test fixture içinde "
        "related_dispute_item_id bulunamadı."
    )

    dispute_results = (
        repository.find_by_dispute_item(
            case_id,
            sample_dispute_item_id,
        )
    )

    assert dispute_results

    assert all(
        sample_dispute_item_id
        in record[
            "fact"
        ].get(
            "related_dispute_item_ids",
            [],
        )
        for record
        in dispute_results
    )

    print(
        "T08 Dispute item filter:",
        "PASS"
    )


    # ========================================================
    # T09 - CONFIDENCE FILTER
    # ========================================================

    confidence_threshold = 0.99

    confidence_results = (
        repository.find_facts(
            case_id=case_id,
            min_confidence=
                confidence_threshold,
        )
    )

    assert all(
        record[
            "fact"
        ].get(
            "confidence",
            0,
        )
        >= confidence_threshold
        for record
        in confidence_results
    )

    print(
        "T09 Confidence filter:",
        "PASS"
    )


    # ========================================================
    # T10 - SUMMARY CONSISTENCY
    # ========================================================

    summary = (
        repository.get_case_summary(
            case_id
        )
    )

    assert (
        summary[
            "fact_count"
        ]
        == len(
            facts
        )
    )

    assert (
        summary[
            "extraction_count"
        ]
        == len(
            extractions
        )
    )

    assert (
        summary[
            "source_document_count"
        ]
        == len(
            {
                record[
                    "source_document_id"
                ]
                for record
                in facts
            }
        )
    )

    print(
        "T10 Summary consistency:",
        "PASS"
    )


    # ========================================================
    # OUTPUT
    # ========================================================

    print()

    print(
        "Case:",
        summary[
            "case_id"
        ]
    )

    print(
        "Repository version:",
        summary[
            "repository_version"
        ]
    )

    print(
        "Canonical extraction:",
        summary[
            "extraction_count"
        ]
    )

    print(
        "Fact:",
        summary[
            "fact_count"
        ]
    )

    print(
        "Source document:",
        summary[
            "source_document_count"
        ]
    )

    print(
        "Source IDs:",
        summary[
            "source_document_ids"
        ]
    )

    print(
        "Fact kinds:",
        summary[
            "fact_kinds"
        ]
    )

    print(
        "Verification:",
        summary[
            "verification_states"
        ]
    )

    print(
        "Extractor versions:",
        summary[
            "extractor_versions"
        ]
    )

    print()

    print(
        "======================================"
    )

    print(
        " FACT REPOSITORY V1.1: 10/10 PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    run_basic_tests()