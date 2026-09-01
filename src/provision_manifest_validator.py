# ============================================================
# VERGİ AI - PROVISION MANIFEST VALIDATOR V1.1
#
# V1.1 YENİ:
#
# applicability.completion_evidence
#
# artık validator tarafından kontrol edilir.
#
#
# KRİTİK KURAL:
#
# windows_complete_verified = True
#
# ise:
#
# 1. windows_complete = True olmalı
# 2. en az bir window bulunmalı
# 3. bütün windows verified=True olmalı
# 4. en az bir completion_evidence bulunmalı
# 5. en az bir completion_evidence verified=True olmalı
#
#
# Böylece:
#
# "Bütün süreleri ve uzatmaları kontrol ettik"
#
# iddiası kanıtsız boolean olamaz.
# ============================================================


import json
import os
from datetime import datetime
from urllib.parse import urlparse

from jsonschema import (
    Draft202012Validator,
    FormatChecker
)


VALIDATOR_VERSION = "1.1"


# ============================================================
# PATHS
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
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

PROVISIONS_SCHEMA_PATH = os.path.join(
    DATA_DIR,
    "provisions.schema.json"
)

DOCUMENTS_PATH = os.path.join(
    DATA_DIR,
    "documents.json"
)


# ============================================================
# JSON LOAD
# ============================================================

def load_json(
    path
):

    if not os.path.exists(
        path
    ):

        raise FileNotFoundError(
            f"Dosya bulunamadı:\n{path}"
        )

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as file:

        return json.load(
            file
        )


# ============================================================
# NORMALIZE
# ============================================================

def normalize(
    value
):

    if value is None:

        return None

    return str(
        value
    ).strip()


# ============================================================
# DATE
# ============================================================

def parse_date(
    value
):

    if value is None:

        return None

    if isinstance(
        value,
        datetime
    ):

        return value.date()

    try:

        return datetime.strptime(
            str(
                value
            ).strip(),
            "%Y-%m-%d"
        ).date()

    except (
        ValueError,
        TypeError
    ):

        return None


# ============================================================
# JSON PATH
# ============================================================

def format_json_path(
    path_parts
):

    if not path_parts:

        return "$"

    output = "$"

    for part in path_parts:

        if isinstance(
            part,
            int
        ):

            output += (
                f"[{part}]"
            )

        else:

            output += (
                f".{part}"
            )

    return output


# ============================================================
# SCHEMA
# ============================================================

def validate_schema(
    data,
    schema
):

    errors = []

    Draft202012Validator.check_schema(
        schema
    )

    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker()
    )

    schema_errors = sorted(
        validator.iter_errors(
            data
        ),
        key=lambda error:
            list(
                error.absolute_path
            )
    )

    for error in schema_errors:

        location = format_json_path(
            list(
                error.absolute_path
            )
        )

        errors.append(
            "Schema hatası "
            f"{location}: "
            f"{error.message}"
        )

    return errors


# ============================================================
# DOCUMENT INDEX
# ============================================================

def build_document_index(
    documents_manifest
):

    document_index = {}

    documents = documents_manifest.get(
        "documents",
        []
    )

    for document in documents:

        document_id = normalize(
            document.get(
                "document_id"
            )
        )

        if document_id:

            document_index[
                document_id
            ] = document

    return document_index


# ============================================================
# URL
# ============================================================

def is_probably_http_url(
    value
):

    if not value:

        return True

    try:

        parsed = urlparse(
            value
        )

    except Exception:

        return False

    return (
        parsed.scheme
        in {
            "http",
            "https"
        }
        and bool(
            parsed.netloc
        )
    )


# ============================================================
# EVIDENCE ID REGISTRY
#
# Provision version içinde evidence_id değerlerinin
# tekrar kullanılmasını engeller.
#
# Çünkü ileride evidence provenance takibinde
# evidence_id'nin tekil olması işimizi kolaylaştırır.
# ============================================================

def register_evidence_id(
    evidence_id,
    evidence_location,
    evidence_registry,
    errors
):

    if not evidence_id:

        return

    if evidence_id in evidence_registry:

        previous_location = (
            evidence_registry[
                evidence_id
            ]
        )

        errors.append(
            f"{evidence_location}: "
            "duplicate evidence_id bulundu: "
            f"{evidence_id}. "
            "İlk kullanım: "
            f"{previous_location}"
        )

        return

    evidence_registry[
        evidence_id
    ] = evidence_location


# ============================================================
# EVIDENCE VALIDATION
# ============================================================

def validate_evidence_list(
    evidence_list,
    location,
    document_index,
    errors,
    warnings,
    evidence_registry,
    require_verified_evidence=False
):

    if not isinstance(
        evidence_list,
        list
    ):

        return {
            "count": 0,
            "verified_count": 0
        }

    verified_count = 0

    for evidence_index, evidence in enumerate(
        evidence_list
    ):

        evidence_location = (
            f"{location}.evidence"
            f"[{evidence_index}]"
        )

        evidence_id = normalize(
            evidence.get(
                "evidence_id"
            )
        )

        register_evidence_id(
            evidence_id=
                evidence_id,

            evidence_location=
                evidence_location,

            evidence_registry=
                evidence_registry,

            errors=
                errors
        )

        verified = (
            evidence.get(
                "verified"
            )
            is True
        )

        if verified:

            verified_count += 1

        source_document_id = normalize(
            evidence.get(
                "source_document_id"
            )
        )

        if (
            source_document_id
            and source_document_id
            not in document_index
        ):

            errors.append(
                f"{evidence_location}: "
                "source_document_id "
                "documents.json içinde bulunamadı: "
                f"{source_document_id}"
            )

        source_url = normalize(
            evidence.get(
                "source_url"
            )
        )

        if (
            source_url
            and not is_probably_http_url(
                source_url
            )
        ):

            warnings.append(
                f"{evidence_location}: "
                "source_url HTTP/HTTPS URL gibi görünmüyor: "
                f"{source_url}"
            )

        # ====================================================
        # VERIFIED EVIDENCE SOURCE CHECK
        #
        # Bir evidence verified=True ise en azından:
        #
        # - source_document_id
        # veya
        # - source_url
        #
        # olmasını istiyoruz.
        #
        # Citation tek başına provenance değildir.
        # ====================================================

        if (
            verified
            and not source_document_id
            and not source_url
        ):

            errors.append(
                f"{evidence_location}: "
                "verified evidence için "
                "source_document_id veya source_url gerekiyor."
            )

    if (
        require_verified_evidence
        and verified_count == 0
    ):

        errors.append(
            f"{location}: "
            "verified kayıt için en az bir "
            "verified evidence gerekiyor."
        )

    return {
        "count":
            len(
                evidence_list
            ),

        "verified_count":
            verified_count
    }


# ============================================================
# LOCATOR
# ============================================================

def validate_locator(
    provision,
    location,
    errors
):

    locator = provision.get(
        "locator",
        {}
    )

    madde = normalize(
        locator.get(
            "madde"
        )
    )

    fikra = normalize(
        locator.get(
            "fikra"
        )
    )

    bent = normalize(
        locator.get(
            "bent"
        )
    )

    if not madde:

        errors.append(
            f"{location}.locator: "
            "Provision kaydı için madde boş olamaz."
        )

    if (
        bent
        and not fikra
    ):

        errors.append(
            f"{location}.locator: "
            "bent tanımlıysa fikra da tanımlı olmalıdır."
        )

    return (
        madde,
        fikra,
        bent
    )


# ============================================================
# FORMAL
# ============================================================

def validate_formal(
    provision,
    location,
    document_index,
    errors,
    warnings,
    evidence_registry
):

    formal = provision.get(
        "formal",
        {}
    )

    verified = (
        formal.get(
            "verified"
        )
        is True
    )

    status = normalize(
        formal.get(
            "status"
        )
    )

    valid_from = parse_date(
        formal.get(
            "valid_from"
        )
    )

    valid_through = parse_date(
        formal.get(
            "valid_through"
        )
    )

    repeal_effective_date = parse_date(
        formal.get(
            "repeal_effective_date"
        )
    )

    # ========================================================
    # DATE LOGIC
    # ========================================================

    if (
        valid_from is not None
        and valid_through is not None
        and valid_from > valid_through
    ):

        errors.append(
            f"{location}.formal: "
            "valid_from, valid_through tarihinden "
            "sonra olamaz."
        )

    if (
        valid_from is not None
        and repeal_effective_date is not None
        and valid_from
        >= repeal_effective_date
    ):

        errors.append(
            f"{location}.formal: "
            "repeal_effective_date, valid_from "
            "tarihinden sonra olmalıdır."
        )

    if (
        valid_through is not None
        and repeal_effective_date is not None
        and valid_through
        >= repeal_effective_date
    ):

        errors.append(
            f"{location}.formal: "
            "valid_through, repeal_effective_date "
            "tarihinden önce olmalıdır."
        )

    # ========================================================
    # VERIFIED FORMAL
    # ========================================================

    if verified:

        if status == "unknown":

            errors.append(
                f"{location}.formal: "
                "verified=True iken status=unknown olamaz."
            )

        if (
            status
            in {
                "active",
                "amended",
                "partially_repealed"
            }
            and valid_from is None
        ):

            errors.append(
                f"{location}.formal: "
                "verified active/amended/"
                "partially_repealed provision için "
                "valid_from gerekiyor."
            )

        if (
            status
            in {
                "repealed",
                "historical"
            }
            and repeal_effective_date is None
        ):

            errors.append(
                f"{location}.formal: "
                "verified repealed/historical provision için "
                "repeal_effective_date gerekiyor."
            )

    else:

        if status != "unknown":

            warnings.append(
                f"{location}.formal: "
                "formal.verified=False olmasına rağmen "
                f"status={status}. "
                "Policy bunu kesin formal sonuç olarak "
                "kullanmamalıdır."
            )

    validate_evidence_list(
        evidence_list=
            formal.get(
                "evidence",
                []
            ),

        location=
            f"{location}.formal",

        document_index=
            document_index,

        errors=
            errors,

        warnings=
            warnings,

        evidence_registry=
            evidence_registry,

        require_verified_evidence=
            verified
    )


# ============================================================
# WINDOW DATE LOGIC
# ============================================================

def validate_window_dates(
    window,
    location,
    errors
):

    start = parse_date(
        window.get(
            "start"
        )
    )

    end = parse_date(
        window.get(
            "end"
        )
    )

    if (
        start is None
        and end is None
    ):

        errors.append(
            f"{location}: "
            "Applicability window için start ve end "
            "aynı anda null olamaz."
        )

    if (
        start is not None
        and end is not None
        and start > end
    ):

        errors.append(
            f"{location}: "
            "window.start, window.end tarihinden "
            "sonra olamaz."
        )

    return (
        start,
        end
    )


# ============================================================
# WINDOW OVERLAP
# ============================================================

def windows_overlap(
    first_start,
    first_end,
    second_start,
    second_end
):

    if (
        first_start is None
        or first_end is None
        or second_start is None
        or second_end is None
    ):

        return False

    return (
        first_start <= second_end
        and second_start <= first_end
    )


# ============================================================
# APPLICABILITY
# ============================================================

def validate_applicability(
    provision,
    location,
    document_index,
    errors,
    warnings,
    evidence_registry
):

    applicability = provision.get(
        "applicability",
        {}
    )

    windows_complete = (
        applicability.get(
            "windows_complete"
        )
        is True
    )

    windows_complete_verified = (
        applicability.get(
            "windows_complete_verified"
        )
        is True
    )

    completion_evidence = applicability.get(
        "completion_evidence",
        []
    )

    windows = applicability.get(
        "windows",
        []
    )

    if not isinstance(
        windows,
        list
    ):

        return

    # ========================================================
    # COMPLETION EVIDENCE
    # ========================================================

    completion_evidence_result = (
        validate_evidence_list(
            evidence_list=
                completion_evidence,

            location=
                (
                    f"{location}."
                    "applicability.completion_evidence"
                ),

            document_index=
                document_index,

            errors=
                errors,

            warnings=
                warnings,

            evidence_registry=
                evidence_registry,

            require_verified_evidence=
                windows_complete_verified
        )
    )

    completion_evidence_count = (
        completion_evidence_result[
            "count"
        ]
    )

    verified_completion_evidence_count = (
        completion_evidence_result[
            "verified_count"
        ]
    )

    # ========================================================
    # COMPLETENESS LOGIC
    # ========================================================

    if (
        windows_complete_verified
        and not windows_complete
    ):

        errors.append(
            f"{location}.applicability: "
            "windows_complete_verified=True iken "
            "windows_complete=False olamaz."
        )

    if (
        windows_complete
        and not windows
    ):

        errors.append(
            f"{location}.applicability: "
            "windows_complete=True ancak hiç window yok."
        )

    # ========================================================
    # COMPLETION CLAIM MUST HAVE EVIDENCE
    # ========================================================

    if windows_complete_verified:

        if completion_evidence_count == 0:

            errors.append(
                f"{location}.applicability: "
                "windows_complete_verified=True için "
                "completion_evidence boş olamaz."
            )

        if (
            verified_completion_evidence_count
            == 0
        ):

            errors.append(
                f"{location}.applicability: "
                "windows_complete_verified=True için "
                "en az bir verified completion_evidence "
                "gerekiyor."
            )

    # ========================================================
    # COMPLETION EVIDENCE EXISTS BUT CLAIM NOT VERIFIED
    #
    # Hata değil.
    #
    # Araştırma sürüyor olabilir.
    # ========================================================

    if (
        completion_evidence_count > 0
        and not windows_complete_verified
    ):

        warnings.append(
            f"{location}.applicability: "
            "completion_evidence mevcut ancak "
            "windows_complete_verified=False. "
            "Bu araştırma aşamasında normal olabilir."
        )

    seen_window_ids = set()

    parsed_windows = []

    all_windows_verified = True

    # ========================================================
    # WINDOWS
    # ========================================================

    for window_index, window in enumerate(
        windows
    ):

        window_location = (
            f"{location}.applicability.windows"
            f"[{window_index}]"
        )

        window_id = normalize(
            window.get(
                "window_id"
            )
        )

        if window_id:

            if window_id in seen_window_ids:

                errors.append(
                    f"{window_location}: "
                    "duplicate window_id: "
                    f"{window_id}"
                )

            seen_window_ids.add(
                window_id
            )

        verified = (
            window.get(
                "verified"
            )
            is True
        )

        if not verified:

            all_windows_verified = False

        start, end = validate_window_dates(
            window=
                window,

            location=
                window_location,

            errors=
                errors
        )

        # ====================================================
        # POLICY V1 ONLY SUPPORTS INCLUSIVE WINDOWS
        # ====================================================

        if (
            window.get(
                "start_inclusive"
            )
            is False
        ):

            errors.append(
                f"{window_location}: "
                "start_inclusive=False henüz "
                "Provision Policy V1 tarafından desteklenmiyor."
            )

        if (
            window.get(
                "end_inclusive"
            )
            is False
        ):

            errors.append(
                f"{window_location}: "
                "end_inclusive=False henüz "
                "Provision Policy V1 tarafından desteklenmiyor."
            )

        validate_evidence_list(
            evidence_list=
                window.get(
                    "evidence",
                    []
                ),

            location=
                window_location,

            document_index=
                document_index,

            errors=
                errors,

            warnings=
                warnings,

            evidence_registry=
                evidence_registry,

            require_verified_evidence=
                verified
        )

        parsed_windows.append(
            {
                "window_id":
                    window_id,

                "start":
                    start,

                "end":
                    end,

                "type":
                    normalize(
                        window.get(
                            "type"
                        )
                    )
            }
        )

    # ========================================================
    # COMPLETE VERIFIED REQUIRES ALL WINDOWS VERIFIED
    # ========================================================

    if windows_complete_verified:

        if not all_windows_verified:

            errors.append(
                f"{location}.applicability: "
                "windows_complete_verified=True iken "
                "tüm windows verified=True olmalıdır."
            )

    # ========================================================
    # COMPLETE TRUE BUT NOT VERIFIED
    #
    # Allowed, but warn.
    #
    # windows_complete can be a working hypothesis.
    # ========================================================

    if (
        windows_complete
        and not windows_complete_verified
    ):

        warnings.append(
            f"{location}.applicability: "
            "windows_complete=True ancak "
            "windows_complete_verified=False. "
            "Completeness kesin hukuki sonuç için "
            "kullanılamaz."
        )

    # ========================================================
    # OVERLAP WARNINGS
    # ========================================================

    for first_index in range(
        len(
            parsed_windows
        )
    ):

        for second_index in range(
            first_index + 1,
            len(
                parsed_windows
            )
        ):

            first = parsed_windows[
                first_index
            ]

            second = parsed_windows[
                second_index
            ]

            if windows_overlap(
                first_start=
                    first[
                        "start"
                    ],

                first_end=
                    first[
                        "end"
                    ],

                second_start=
                    second[
                        "start"
                    ],

                second_end=
                    second[
                        "end"
                    ]
            ):

                warnings.append(
                    f"{location}.applicability: "
                    "Applicability windows örtüşüyor: "
                    f"{first['window_id']} ve "
                    f"{second['window_id']}. "
                    "Bu hukuken geçerli olabilir ancak "
                    "kontrol edilmelidir."
                )


# ============================================================
# SUBJECT PERIODS
# ============================================================

def validate_subject_periods(
    provision,
    location,
    document_index,
    errors,
    warnings,
    evidence_registry
):

    subject_periods = provision.get(
        "subject_periods",
        []
    )

    if not isinstance(
        subject_periods,
        list
    ):

        return

    seen_period_ids = set()

    for period_index, period in enumerate(
        subject_periods
    ):

        period_location = (
            f"{location}.subject_periods"
            f"[{period_index}]"
        )

        period_id = normalize(
            period.get(
                "period_id"
            )
        )

        if period_id:

            if period_id in seen_period_ids:

                errors.append(
                    f"{period_location}: "
                    "duplicate period_id: "
                    f"{period_id}"
                )

            seen_period_ids.add(
                period_id
            )

        start = parse_date(
            period.get(
                "start"
            )
        )

        end = parse_date(
            period.get(
                "end"
            )
        )

        if (
            start is None
            and end is None
        ):

            warnings.append(
                f"{period_location}: "
                "subject period start/end boş. "
                "Yalnızca label üzerinden dönem yorumu "
                "yapılmamalıdır."
            )

        if (
            start is not None
            and end is not None
            and start > end
        ):

            errors.append(
                f"{period_location}: "
                "subject period start, end tarihinden "
                "sonra olamaz."
            )

        verified = (
            period.get(
                "verified"
            )
            is True
        )

        validate_evidence_list(
            evidence_list=
                period.get(
                    "evidence",
                    []
                ),

            location=
                period_location,

            document_index=
                document_index,

            errors=
                errors,

            warnings=
                warnings,

            evidence_registry=
                evidence_registry,

            require_verified_evidence=
                verified
        )


# ============================================================
# RELATIONS
# ============================================================

def validate_relations(
    provision,
    location,
    provision_ids,
    version_to_provision,
    document_index,
    errors,
    warnings,
    evidence_registry
):

    relations = provision.get(
        "relations",
        []
    )

    if not isinstance(
        relations,
        list
    ):

        return

    current_provision_id = normalize(
        provision.get(
            "provision_id"
        )
    )

    current_version_id = normalize(
        provision.get(
            "provision_version_id"
        )
    )

    seen_relations = set()

    for relation_index, relation in enumerate(
        relations
    ):

        relation_location = (
            f"{location}.relations"
            f"[{relation_index}]"
        )

        relation_type = normalize(
            relation.get(
                "type"
            )
        )

        target_provision_id = normalize(
            relation.get(
                "target_provision_id"
            )
        )

        target_version_id = normalize(
            relation.get(
                "target_provision_version_id"
            )
        )

        relation_key = (
            relation_type,
            target_provision_id,
            target_version_id
        )

        if relation_key in seen_relations:

            errors.append(
                f"{relation_location}: "
                "Duplicate relation bulundu."
            )

        seen_relations.add(
            relation_key
        )

        if (
            target_provision_id
            not in provision_ids
        ):

            errors.append(
                f"{relation_location}: "
                "target_provision_id bulunamadı: "
                f"{target_provision_id}"
            )

        if target_version_id:

            target_version_owner = (
                version_to_provision.get(
                    target_version_id
                )
            )

            if target_version_owner is None:

                errors.append(
                    f"{relation_location}: "
                    "target_provision_version_id bulunamadı: "
                    f"{target_version_id}"
                )

            elif (
                target_version_owner
                != target_provision_id
            ):

                errors.append(
                    f"{relation_location}: "
                    "target_provision_version_id başka "
                    "bir provision_id'ye ait. "
                    f"Beklenen={target_provision_id}, "
                    f"gerçek={target_version_owner}"
                )

        if (
            target_provision_id
            == current_provision_id
            and target_version_id
            == current_version_id
        ):

            errors.append(
                f"{relation_location}: "
                "Bir provision version kendisine "
                "relation veremez."
            )

        if (
            target_provision_id
            == current_provision_id
            and target_version_id is None
            and relation_type
            in {
                "amends",
                "supersedes"
            }
        ):

            warnings.append(
                f"{relation_location}: "
                f"{relation_type} relation aynı provision_id'yi "
                "hedefliyor ancak target version belirtilmemiş."
            )

        verified = (
            relation.get(
                "verified"
            )
            is True
        )

        validate_evidence_list(
            evidence_list=
                relation.get(
                    "evidence",
                    []
                ),

            location=
                relation_location,

            document_index=
                document_index,

            errors=
                errors,

            warnings=
                warnings,

            evidence_registry=
                evidence_registry,

            require_verified_evidence=
                verified
        )


# ============================================================
# VERIFICATION STATE
# ============================================================

def validate_verification_state(
    provision,
    location,
    errors,
    warnings
):

    state = normalize(
        provision.get(
            "verification_state"
        )
    )

    formal = provision.get(
        "formal",
        {}
    )

    applicability = provision.get(
        "applicability",
        {}
    )

    subject_periods = provision.get(
        "subject_periods",
        []
    )

    formal_verified = (
        formal.get(
            "verified"
        )
        is True
    )

    windows = applicability.get(
        "windows",
        []
    )

    verified_windows = [

        window

        for window in windows

        if (
            isinstance(
                window,
                dict
            )
            and window.get(
                "verified"
            )
            is True
        )
    ]

    verified_subject_periods = [

        period

        for period in subject_periods

        if (
            isinstance(
                period,
                dict
            )
            and period.get(
                "verified"
            )
            is True
        )
    ]

    completion_verified = (
        applicability.get(
            "windows_complete_verified"
        )
        is True
    )

    any_verified_component = any(
        [
            formal_verified,
            bool(
                verified_windows
            ),
            bool(
                verified_subject_periods
            ),
            completion_verified
        ]
    )

    if (
        state == "unverified"
        and any_verified_component
    ):

        warnings.append(
            f"{location}: "
            "verification_state=unverified ancak "
            "en az bir alt bileşen verified. "
            "partially_verified düşünülebilir."
        )

    if (
        state == "partially_verified"
        and not any_verified_component
    ):

        errors.append(
            f"{location}: "
            "verification_state=partially_verified ancak "
            "hiçbir alt bileşen verified değil."
        )

    if (
        state == "verified"
        and not formal_verified
    ):

        errors.append(
            f"{location}: "
            "verification_state=verified için "
            "formal.verified=True olmalıdır."
        )


# ============================================================
# MAIN MANIFEST VALIDATION
# ============================================================

def validate_manifest(
    provisions_manifest,
    documents_manifest
):

    errors = []

    warnings = []

    document_index = (
        build_document_index(
            documents_manifest
        )
    )

    provisions = provisions_manifest.get(
        "provisions",
        []
    )

    provision_ids = set()

    version_to_provision = {}

    provision_identity = {}

    # ========================================================
    # FIRST PASS
    # ========================================================

    for provision_index, provision in enumerate(
        provisions
    ):

        location = (
            f"$.provisions[{provision_index}]"
        )

        provision_id = normalize(
            provision.get(
                "provision_id"
            )
        )

        version_id = normalize(
            provision.get(
                "provision_version_id"
            )
        )

        document_id = normalize(
            provision.get(
                "document_id"
            )
        )

        locator = provision.get(
            "locator",
            {}
        )

        identity = (
            document_id,
            normalize(
                locator.get(
                    "madde"
                )
            ),
            normalize(
                locator.get(
                    "fikra"
                )
            ),
            normalize(
                locator.get(
                    "bent"
                )
            )
        )

        if provision_id:

            provision_ids.add(
                provision_id
            )

            if provision_id not in provision_identity:

                provision_identity[
                    provision_id
                ] = identity

            elif (
                provision_identity[
                    provision_id
                ]
                != identity
            ):

                errors.append(
                    f"{location}: "
                    "Aynı provision_id farklı "
                    "document/locator kimliğiyle kullanılmış: "
                    f"{provision_id}"
                )

        if version_id:

            if version_id in version_to_provision:

                errors.append(
                    f"{location}: "
                    "Duplicate provision_version_id: "
                    f"{version_id}"
                )

            else:

                version_to_provision[
                    version_id
                ] = provision_id

    # ========================================================
    # SECOND PASS
    # ========================================================

    for provision_index, provision in enumerate(
        provisions
    ):

        location = (
            f"$.provisions[{provision_index}]"
        )

        document_id = normalize(
            provision.get(
                "document_id"
            )
        )

        # ----------------------------------------------------
        # Evidence IDs are unique inside each provision version.
        # ----------------------------------------------------

        evidence_registry = {}

        # ====================================================
        # DOCUMENT
        # ====================================================

        if (
            document_id
            not in document_index
        ):

            errors.append(
                f"{location}: "
                "document_id documents.json içinde "
                "bulunamadı: "
                f"{document_id}"
            )

        # ====================================================
        # LOCATOR
        # ====================================================

        validate_locator(
            provision=
                provision,

            location=
                location,

            errors=
                errors
        )

        # ====================================================
        # FORMAL
        # ====================================================

        validate_formal(
            provision=
                provision,

            location=
                location,

            document_index=
                document_index,

            errors=
                errors,

            warnings=
                warnings,

            evidence_registry=
                evidence_registry
        )

        # ====================================================
        # APPLICABILITY
        # ====================================================

        validate_applicability(
            provision=
                provision,

            location=
                location,

            document_index=
                document_index,

            errors=
                errors,

            warnings=
                warnings,

            evidence_registry=
                evidence_registry
        )

        # ====================================================
        # SUBJECT PERIODS
        # ====================================================

        validate_subject_periods(
            provision=
                provision,

            location=
                location,

            document_index=
                document_index,

            errors=
                errors,

            warnings=
                warnings,

            evidence_registry=
                evidence_registry
        )

        # ====================================================
        # RELATIONS
        # ====================================================

        validate_relations(
            provision=
                provision,

            location=
                location,

            provision_ids=
                provision_ids,

            version_to_provision=
                version_to_provision,

            document_index=
                document_index,

            errors=
                errors,

            warnings=
                warnings,

            evidence_registry=
                evidence_registry
        )

        # ====================================================
        # VERIFICATION STATE
        # ====================================================

        validate_verification_state(
            provision=
                provision,

            location=
                location,

            errors=
                errors,

            warnings=
                warnings
        )

        # ====================================================
        # ENABLED DOCUMENT
        # ====================================================

        if provision.get(
            "enabled"
        ) is True:

            document = document_index.get(
                document_id
            )

            if document is not None:

                if (
                    document.get(
                        "ingest",
                        {}
                    ).get(
                        "enabled"
                    )
                    is False
                ):

                    warnings.append(
                        f"{location}: "
                        "Provision enabled=True ancak bağlı "
                        "document ingest.enabled=False."
                    )

    return (
        errors,
        warnings
    )


# ============================================================
# SUMMARY
# ============================================================

def build_verification_summary(
    provisions_manifest
):

    counts = {

        "verified":
            0,

        "partially_verified":
            0,

        "unverified":
            0
    }

    for provision in provisions_manifest.get(
        "provisions",
        []
    ):

        state = normalize(
            provision.get(
                "verification_state"
            )
        )

        if state in counts:

            counts[
                state
            ] += 1

    return counts


# ============================================================
# RUN
# ============================================================

def run_validator():

    print(
        "\n======================================"
    )

    print(
        " VERGİ AI - PROVISION MANIFEST"
    )

    print(
        f" VALIDATOR V{VALIDATOR_VERSION}"
    )

    print(
        "======================================"
    )

    try:

        provisions_schema = load_json(
            PROVISIONS_SCHEMA_PATH
        )

        provisions_manifest = load_json(
            PROVISIONS_PATH
        )

        documents_manifest = load_json(
            DOCUMENTS_PATH
        )

    except Exception as error:

        print(
            "\nPROVISIONS MANIFEST GEÇERSİZ"
        )

        print(
            error
        )

        raise SystemExit(
            1
        )

    # ========================================================
    # SCHEMA
    # ========================================================

    schema_errors = validate_schema(
        data=
            provisions_manifest,

        schema=
            provisions_schema
    )

    # ========================================================
    # BUSINESS / LEGAL RULES
    # ========================================================

    validation_errors, warnings = (
        validate_manifest(
            provisions_manifest=
                provisions_manifest,

            documents_manifest=
                documents_manifest
        )
    )

    all_errors = (
        schema_errors
        + validation_errors
    )

    # ========================================================
    # FAILURE
    # ========================================================

    if all_errors:

        print(
            "\nPROVISIONS MANIFEST GEÇERSİZ"
        )

        print(
            "\nHATALAR:"
        )

        for error in all_errors:

            print(
                "-",
                error
            )

        if warnings:

            print(
                "\nUYARILAR:"
            )

            for warning in warnings:

                print(
                    "-",
                    warning
                )

        print(
            "\n======================================"
        )

        raise SystemExit(
            1
        )

    # ========================================================
    # SUCCESS
    # ========================================================

    verification_summary = (
        build_verification_summary(
            provisions_manifest
        )
    )

    print(
        "\nPROVISIONS MANIFEST GEÇERLİ"
    )

    print(
        "Provision version sayısı:",
        len(
            provisions_manifest.get(
                "provisions",
                []
            )
        )
    )

    print(
        "Doğrulanmış:",
        verification_summary[
            "verified"
        ]
    )

    print(
        "Kısmen doğrulanmış:",
        verification_summary[
            "partially_verified"
        ]
    )

    print(
        "Doğrulanmamış:",
        verification_summary[
            "unverified"
        ]
    )

    if warnings:

        print(
            "\nUYARILAR:"
        )

        for warning in warnings:

            print(
                "-",
                warning
            )

    else:

        print(
            "Uyarı yok."
        )

    print(
        "\n======================================"
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    run_validator()