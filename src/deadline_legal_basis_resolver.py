# ============================================================
# VERGİ AI - DEADLINE LEGAL BASIS RESOLVER V1.2
#
# AMAÇ
# ----
#
# Deadline Rule Registry içindeki legal_basis_refs değerlerini:
#
#   1. Provision Repository
#   2. Provision Version Policy
#   3. Verification / formal evidence safety
#
# zinciri üzerinden deterministik olarak çözmek.
#
#
# V1.2 DÜZELTMESİ
# ---------------
#
# Provision Repository resolve_provisions() doğrudan provision
# döndürmez.
#
# Gerçek return shape:
#
# {
#     "status": "resolved",
#     "match_type": "...",
#     "score": ...,
#     "provision_id": "...",
#     "candidates": [
#         { FULL PROVISION VERSION },
#         ...
#     ]
# }
#
# V1.1 wrapper objesini provision sanıyordu.
# V1.2 gerçek candidates[] listesini kullanır.
#
#
# VERSION SELECTION
# -----------------
#
# candidates[]
#      ↓
# provision_version_policy.select_provision_versions(...)
#      ↓
# selection_status == "selected"
#      ↓
# exactly one selected candidate
#
#
# ACTIVATION SAFETY
# -----------------
#
# Seçilmiş provision version:
#
#   verification_state == "verified"
#   formal.verified     == True
#   formal.status       == "active"
#   en az bir verified formal evidence
#
# sağlamadan activation_eligible=True OLAMAZ.
#
#
# TEMPORAL MODES
# --------------
#
# current
# historical_date
# neutral
#
# Default:
#     current
#
# neutral:
#     version seçimi yapılmadığından activation fail-closed.
#
# historical_date:
#     query_date zorunludur.
#
#
# BU KATMAN:
#
# - deadline hesaplamaz
# - deadline rule'u active yapmaz
# - özel kanun önceliğini çözmez
# - insan doğrulamasını değiştirmez
#
# ============================================================


import argparse
import json
import re
import sys

from pathlib import Path


import provision_repository as provision_repo
import provision_version_policy as version_policy

from deadline_rule_validator import (
    validate_deadline_rules,
)


# ============================================================
# VERSION
# ============================================================

DEADLINE_LEGAL_BASIS_RESOLVER_VERSION = "1.2"


# ============================================================
# TEMPORAL
# ============================================================

DEFAULT_TEMPORAL_MODE = "current"

SUPPORTED_TEMPORAL_MODES = {
    "neutral",
    "historical_date",
    "current",
}


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

DEFAULT_RULESET_PATH = (
    DATA_DIR
    / "deadline_rules"
    / "deadline_rules.json"
)


# ============================================================
# DOCUMENT PREFIX MAPPING
# ============================================================

LEGAL_DOCUMENT_PREFIXES = {
    "IYUK_2577":
        "kanun_2577",

    "VUK_213":
        "kanun_213",

    "KDVK_3065":
        "kanun_3065",
}


# ============================================================
# EXCEPTION
# ============================================================

class DeadlineLegalBasisResolverError(
    Exception
):
    pass


# ============================================================
# JSON
# ============================================================

def load_json(
    path,
):

    path = Path(
        path
    )

    if not path.exists():

        raise FileNotFoundError(
            f"JSON dosyası bulunamadı:\n{path}"
        )

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:

        return json.load(
            file
        )


# ============================================================
# NORMALIZE
# ============================================================

def normalize_component(
    value,
):

    if value is None:

        return None

    value = str(
        value
    ).strip()

    if not value:

        return None

    return value


# ============================================================
# LEGAL BASIS REF PARSER
#
# Örnek:
#
# IYUK_2577_m7
# IYUK_2577_m7_1
# IYUK_2577_m7_2_b
# IYUK_2577_m8_1
# ============================================================

LEGAL_REF_PATTERN = re.compile(
    r"^(?P<prefix>[A-Za-zÇĞİÖŞÜçğıöşü]+)"
    r"_(?P<number>\d+)"
    r"_m(?P<madde>\d+[A-Za-z]?)"
    r"(?:_(?P<fikra>\d+))?"
    r"(?:_(?P<bent>[A-Za-zÇĞİÖŞÜçğıöşü]+))?$"
)


def parse_legal_basis_ref(
    legal_basis_ref,
):

    if not isinstance(
        legal_basis_ref,
        str,
    ):

        return {
            "valid":
                False,

            "legal_basis_ref":
                legal_basis_ref,

            "error":
                "legal_basis_ref string değil.",
        }

    value = legal_basis_ref.strip()

    match = LEGAL_REF_PATTERN.fullmatch(
        value
    )

    if not match:

        return {
            "valid":
                False,

            "legal_basis_ref":
                legal_basis_ref,

            "error":
                "Desteklenmeyen legal basis ref formatı.",
        }

    prefix = (
        match.group(
            "prefix"
        )
        .upper()
    )

    number = match.group(
        "number"
    )

    document_key = (
        f"{prefix}_{number}"
    )

    document_id = (
        LEGAL_DOCUMENT_PREFIXES.get(
            document_key,
            f"kanun_{number}",
        )
    )

    return {
        "valid":
            True,

        "legal_basis_ref":
            value,

        "prefix":
            prefix,

        "law_number":
            number,

        "document_key":
            document_key,

        "document_id":
            document_id,

        "madde":
            normalize_component(
                match.group(
                    "madde"
                )
            ),

        "fikra":
            normalize_component(
                match.group(
                    "fikra"
                )
            ),

        "bent":
            normalize_component(
                match.group(
                    "bent"
                )
            ),

        "known_document_prefix":
            document_key
            in LEGAL_DOCUMENT_PREFIXES,

        "error":
            None,
    }


# ============================================================
# TEMPORAL INPUT VALIDATION
# ============================================================

def validate_temporal_input(
    temporal_mode,
    query_date,
):

    if temporal_mode not in SUPPORTED_TEMPORAL_MODES:

        raise DeadlineLegalBasisResolverError(
            "Desteklenmeyen temporal_mode: "
            f"{temporal_mode}"
        )

    if (
        temporal_mode
        == "historical_date"
        and query_date is None
    ):

        raise DeadlineLegalBasisResolverError(
            "historical_date temporal mode için "
            "query_date zorunludur."
        )


# ============================================================
# MANIFEST DISCOVERY
# ============================================================

def candidate_manifest_paths():

    candidates = []

    for (
        name,
        value,
    ) in vars(
        provision_repo
    ).items():

        normalized_name = (
            str(
                name
            )
            .casefold()
        )

        if (
            "manifest"
            not in normalized_name
        ):

            continue

        if not isinstance(
            value,
            (
                str,
                Path,
            ),
        ):

            continue

        try:

            path = Path(
                value
            )

        except Exception:

            continue

        if not path.is_absolute():

            path = (
                BASE_DIR
                / path
            )

        candidates.append(
            path
        )

    candidates.extend(
        [
            DATA_DIR
            / "provisions.json",

            DATA_DIR
            / "provisions_manifest.json",

            DATA_DIR
            / "provision_manifest.json",

            DATA_DIR
            / "manifests"
            / "provisions.json",

            DATA_DIR
            / "manifests"
            / "provisions_manifest.json",
        ]
    )

    if DATA_DIR.exists():

        for path in DATA_DIR.rglob(
            "*.json"
        ):

            name = (
                path.name
                .casefold()
            )

            if (
                "provision"
                in name
                and "schema"
                not in name
            ):

                candidates.append(
                    path
                )

    unique = []

    seen = set()

    for path in candidates:

        try:

            resolved = (
                path.resolve()
            )

        except Exception:

            continue

        key = str(
            resolved
        )

        if key in seen:

            continue

        seen.add(
            key
        )

        unique.append(
            resolved
        )

    return unique


def discover_manifest_path():

    attempted = []

    for path in candidate_manifest_paths():

        attempted.append(
            str(
                path
            )
        )

        if not path.exists():

            continue

        if not path.is_file():

            continue

        try:

            manifest = (
                provision_repo
                .load_provisions_manifest(
                    path
                )
            )

            enabled = (
                provision_repo
                .get_enabled_provisions(
                    manifest
                )
            )

            if enabled is not None:

                return path

        except Exception:

            continue

    raise DeadlineLegalBasisResolverError(
        "Provision manifest otomatik bulunamadı.\n"
        "Denenen yollar:\n- "
        + "\n- ".join(
            attempted
        )
    )


# ============================================================
# VERIFIED FORMAL EVIDENCE
# ============================================================

def get_verified_formal_evidence(
    provision,
):

    formal = provision.get(
        "formal",
        {}
    )

    if not isinstance(
        formal,
        dict,
    ):

        return []

    evidence = formal.get(
        "evidence",
        []
    )

    if not isinstance(
        evidence,
        list,
    ):

        return []

    return [
        item
        for item in evidence
        if (
            isinstance(
                item,
                dict,
            )
            and item.get(
                "verified"
            )
            is True
        )
    ]


# ============================================================
# ACTIVATION SAFETY
# ============================================================

def evaluate_provision_activation(
    provision,
):

    blockers = []

    if not isinstance(
        provision,
        dict,
    ):

        return {
            "activation_eligible":
                False,

            "verification_state":
                None,

            "formal_verified":
                False,

            "formal_status":
                None,

            "verified_formal_evidence_count":
                0,

            "activation_blockers": [
                "invalid_provision_object"
            ],
        }

    verification_state = (
        provision.get(
            "verification_state"
        )
    )

    formal = provision.get(
        "formal",
        {}
    )

    if not isinstance(
        formal,
        dict,
    ):

        formal = {}

    formal_verified = (
        formal.get(
            "verified"
        )
        is True
    )

    formal_status = (
        formal.get(
            "status"
        )
    )

    verified_evidence = (
        get_verified_formal_evidence(
            provision
        )
    )

    # --------------------------------------------------------
    # PROVISION VERIFICATION
    # --------------------------------------------------------

    if (
        verification_state
        != "verified"
    ):

        blockers.append(
            (
                "verification_state_not_verified:"
                f"{verification_state}"
            )
        )

    # --------------------------------------------------------
    # FORMAL VERIFICATION
    # --------------------------------------------------------

    if not formal_verified:

        blockers.append(
            "formal_not_verified"
        )

    # --------------------------------------------------------
    # FORMAL STATUS
    # --------------------------------------------------------

    if (
        formal_status
        != "active"
    ):

        blockers.append(
            (
                "formal_status_not_active:"
                f"{formal_status}"
            )
        )

    # --------------------------------------------------------
    # VERIFIED EVIDENCE
    # --------------------------------------------------------

    if not verified_evidence:

        blockers.append(
            "no_verified_formal_evidence"
        )

    return {
        "activation_eligible":
            len(
                blockers
            ) == 0,

        "verification_state":
            verification_state,

        "formal_verified":
            formal_verified,

        "formal_status":
            formal_status,

        "verified_formal_evidence_count":
            len(
                verified_evidence
            ),

        "activation_blockers":
            blockers,
    }


# ============================================================
# NORMALIZE SELECTED PROVISION
# ============================================================

def normalize_selected_provision(
    provision,
):

    safety = (
        evaluate_provision_activation(
            provision
        )
    )

    return {
        "provision_id":
            provision_repo
            .get_provision_id(
                provision
            ),

        "provision_version_id":
            provision_repo
            .get_provision_version_id(
                provision
            ),

        "locator":
            provision_repo
            .get_locator(
                provision
            ),

        "verification_state":
            safety[
                "verification_state"
            ],

        "formal_verified":
            safety[
                "formal_verified"
            ],

        "formal_status":
            safety[
                "formal_status"
            ],

        "verified_formal_evidence_count":
            safety[
                "verified_formal_evidence_count"
            ],

        "activation_eligible":
            safety[
                "activation_eligible"
            ],

        "activation_blockers":
            safety[
                "activation_blockers"
            ],
    }


# ============================================================
# EMPTY RESULT
# ============================================================

def build_unresolved_result(
    legal_basis_ref,
    parsed,
    resolution_state,
    blockers,
    repository_status=None,
    repository_match_type=None,
    repository_score=None,
    repository_candidate_count=0,
    version_selection_status=None,
    selected_version_ids=None,
    error=None,
):

    return {
        "legal_basis_ref":
            legal_basis_ref,

        "resolved":
            False,

        "activation_eligible":
            False,

        "resolution_state":
            resolution_state,

        "parsed":
            parsed,

        "repository_status":
            repository_status,

        "repository_match_type":
            repository_match_type,

        "repository_score":
            repository_score,

        "repository_candidate_count":
            repository_candidate_count,

        "version_selection_status":
            version_selection_status,

        "selected_provision_version_ids":
            selected_version_ids
            or [],

        "selected_provision":
            None,

        "activation_blockers":
            list(
                blockers
            ),

        "error":
            error,
    }


# ============================================================
# RESOLVE ONE LEGAL BASIS
# ============================================================

def resolve_legal_basis(
    legal_basis_ref,
    manifest,
    temporal_mode=DEFAULT_TEMPORAL_MODE,
    query_date=None,
):

    validate_temporal_input(
        temporal_mode,
        query_date,
    )

    parsed = (
        parse_legal_basis_ref(
            legal_basis_ref
        )
    )

    # ========================================================
    # INVALID REFERENCE
    # ========================================================

    if not parsed[
        "valid"
    ]:

        return (
            build_unresolved_result(
                legal_basis_ref=
                    legal_basis_ref,

                parsed=
                    parsed,

                resolution_state=
                    "invalid_reference",

                blockers=[
                    "invalid_reference"
                ],

                error=
                    parsed[
                        "error"
                    ],
            )
        )

    # ========================================================
    # REPOSITORY RESOLUTION
    # ========================================================

    try:

        repository_result = (
            provision_repo
            .resolve_provisions(
                parsed[
                    "document_id"
                ],

                parsed[
                    "madde"
                ],

                parsed[
                    "fikra"
                ],

                parsed[
                    "bent"
                ],

                manifest,
            )
        )

    except Exception as error:

        return (
            build_unresolved_result(
                legal_basis_ref=
                    legal_basis_ref,

                parsed=
                    parsed,

                resolution_state=
                    "repository_error",

                blockers=[
                    "repository_error"
                ],

                error=
                    str(
                        error
                    ),
            )
        )

    if not isinstance(
        repository_result,
        dict,
    ):

        return (
            build_unresolved_result(
                legal_basis_ref=
                    legal_basis_ref,

                parsed=
                    parsed,

                resolution_state=
                    "invalid_repository_result",

                blockers=[
                    "invalid_repository_result"
                ],
            )
        )

    repository_status = (
        repository_result.get(
            "status"
        )
    )

    repository_match_type = (
        repository_result.get(
            "match_type"
        )
    )

    repository_score = (
        repository_result.get(
            "score"
        )
    )

    candidates = (
        repository_result.get(
            "candidates",
            []
        )
    )

    if not isinstance(
        candidates,
        list,
    ):

        candidates = []

    # ========================================================
    # NOT FOUND
    # ========================================================

    if (
        repository_status
        == "not_found"
    ):

        return (
            build_unresolved_result(
                legal_basis_ref=
                    legal_basis_ref,

                parsed=
                    parsed,

                resolution_state=
                    "not_found",

                blockers=[
                    "provision_not_found"
                ],

                repository_status=
                    repository_status,

                repository_match_type=
                    repository_match_type,

                repository_score=
                    repository_score,

                repository_candidate_count=
                    len(
                        candidates
                    ),
            )
        )

    # ========================================================
    # AMBIGUOUS LOCATOR
    # ========================================================

    if (
        repository_status
        == "ambiguous"
    ):

        return (
            build_unresolved_result(
                legal_basis_ref=
                    legal_basis_ref,

                parsed=
                    parsed,

                resolution_state=
                    "ambiguous_provision",

                blockers=[
                    "ambiguous_provision"
                ],

                repository_status=
                    repository_status,

                repository_match_type=
                    repository_match_type,

                repository_score=
                    repository_score,

                repository_candidate_count=
                    len(
                        candidates
                    ),
            )
        )

    # ========================================================
    # UNKNOWN REPOSITORY STATUS
    # ========================================================

    if (
        repository_status
        != "resolved"
    ):

        return (
            build_unresolved_result(
                legal_basis_ref=
                    legal_basis_ref,

                parsed=
                    parsed,

                resolution_state=
                    "unsupported_repository_status",

                blockers=[
                    (
                        "unsupported_repository_status:"
                        f"{repository_status}"
                    )
                ],

                repository_status=
                    repository_status,

                repository_match_type=
                    repository_match_type,

                repository_score=
                    repository_score,

                repository_candidate_count=
                    len(
                        candidates
                    ),
            )
        )

    # ========================================================
    # RESOLVED BUT NO CANDIDATES
    # ========================================================

    if not candidates:

        return (
            build_unresolved_result(
                legal_basis_ref=
                    legal_basis_ref,

                parsed=
                    parsed,

                resolution_state=
                    "resolved_without_candidates",

                blockers=[
                    "resolved_without_candidates"
                ],

                repository_status=
                    repository_status,

                repository_match_type=
                    repository_match_type,

                repository_score=
                    repository_score,

                repository_candidate_count=
                    0,
            )
        )

    # ========================================================
    # VERSION POLICY
    # ========================================================

    try:

        version_result = (
            version_policy
            .select_provision_versions(
                candidates=
                    candidates,

                temporal_mode=
                    temporal_mode,

                query_date=
                    query_date,
            )
        )

    except Exception as error:

        return (
            build_unresolved_result(
                legal_basis_ref=
                    legal_basis_ref,

                parsed=
                    parsed,

                resolution_state=
                    "version_policy_error",

                blockers=[
                    "version_policy_error"
                ],

                repository_status=
                    repository_status,

                repository_match_type=
                    repository_match_type,

                repository_score=
                    repository_score,

                repository_candidate_count=
                    len(
                        candidates
                    ),

                error=
                    str(
                        error
                    ),
            )
        )

    version_selection_status = (
        version_result.get(
            "selection_status"
        )
    )

    selected_candidates = (
        version_result.get(
            "selected_candidates",
            []
        )
    )

    selected_version_ids = (
        version_result.get(
            "selected_provision_version_ids",
            []
        )
    )

    if not isinstance(
        selected_candidates,
        list,
    ):

        selected_candidates = []

    if not isinstance(
        selected_version_ids,
        list,
    ):

        selected_version_ids = []

    # ========================================================
    # NEUTRAL MODE
    #
    # Version policy intentionally does not select a legally
    # applicable version in neutral mode.
    #
    # Activation therefore fails closed.
    # ========================================================

    if (
        version_selection_status
        == "neutral"
    ):

        return (
            build_unresolved_result(
                legal_basis_ref=
                    legal_basis_ref,

                parsed=
                    parsed,

                resolution_state=
                    "version_selection_neutral",

                blockers=[
                    "temporal_version_not_selected"
                ],

                repository_status=
                    repository_status,

                repository_match_type=
                    repository_match_type,

                repository_score=
                    repository_score,

                repository_candidate_count=
                    len(
                        candidates
                    ),

                version_selection_status=
                    version_selection_status,

                selected_version_ids=
                    selected_version_ids,
            )
        )

    # ========================================================
    # VERSION UNKNOWN
    # ========================================================

    if (
        version_selection_status
        == "unknown"
    ):

        return (
            build_unresolved_result(
                legal_basis_ref=
                    legal_basis_ref,

                parsed=
                    parsed,

                resolution_state=
                    "version_unknown",

                blockers=[
                    "temporal_version_unknown"
                ],

                repository_status=
                    repository_status,

                repository_match_type=
                    repository_match_type,

                repository_score=
                    repository_score,

                repository_candidate_count=
                    len(
                        candidates
                    ),

                version_selection_status=
                    version_selection_status,

                selected_version_ids=
                    selected_version_ids,
            )
        )

    # ========================================================
    # VERSION CONFLICT
    # ========================================================

    if (
        version_selection_status
        == "version_conflict"
    ):

        return (
            build_unresolved_result(
                legal_basis_ref=
                    legal_basis_ref,

                parsed=
                    parsed,

                resolution_state=
                    "version_conflict",

                blockers=[
                    "version_conflict"
                ],

                repository_status=
                    repository_status,

                repository_match_type=
                    repository_match_type,

                repository_score=
                    repository_score,

                repository_candidate_count=
                    len(
                        candidates
                    ),

                version_selection_status=
                    version_selection_status,

                selected_version_ids=
                    selected_version_ids,
            )
        )

    # ========================================================
    # VERSION UNRESOLVED
    # ========================================================

    if (
        version_selection_status
        == "version_unresolved"
    ):

        return (
            build_unresolved_result(
                legal_basis_ref=
                    legal_basis_ref,

                parsed=
                    parsed,

                resolution_state=
                    "version_unresolved",

                blockers=[
                    "version_unresolved"
                ],

                repository_status=
                    repository_status,

                repository_match_type=
                    repository_match_type,

                repository_score=
                    repository_score,

                repository_candidate_count=
                    len(
                        candidates
                    ),

                version_selection_status=
                    version_selection_status,

                selected_version_ids=
                    selected_version_ids,
            )
        )

    # ========================================================
    # NO VALID VERSION
    # ========================================================

    if (
        version_selection_status
        == "no_valid_version"
    ):

        return (
            build_unresolved_result(
                legal_basis_ref=
                    legal_basis_ref,

                parsed=
                    parsed,

                resolution_state=
                    "no_valid_version",

                blockers=[
                    "no_valid_version"
                ],

                repository_status=
                    repository_status,

                repository_match_type=
                    repository_match_type,

                repository_score=
                    repository_score,

                repository_candidate_count=
                    len(
                        candidates
                    ),

                version_selection_status=
                    version_selection_status,

                selected_version_ids=
                    selected_version_ids,
            )
        )

    # ========================================================
    # OTHER VERSION POLICY FAILURE
    # ========================================================

    if (
        version_selection_status
        != "selected"
    ):

        return (
            build_unresolved_result(
                legal_basis_ref=
                    legal_basis_ref,

                parsed=
                    parsed,

                resolution_state=
                    "version_selection_failed",

                blockers=[
                    (
                        "version_selection_failed:"
                        f"{version_selection_status}"
                    )
                ],

                repository_status=
                    repository_status,

                repository_match_type=
                    repository_match_type,

                repository_score=
                    repository_score,

                repository_candidate_count=
                    len(
                        candidates
                    ),

                version_selection_status=
                    version_selection_status,

                selected_version_ids=
                    selected_version_ids,
            )
        )

    # ========================================================
    # EXACTLY ONE SELECTED VERSION REQUIRED
    # ========================================================

    if (
        len(
            selected_candidates
        )
        != 1
    ):

        return (
            build_unresolved_result(
                legal_basis_ref=
                    legal_basis_ref,

                parsed=
                    parsed,

                resolution_state=
                    "selected_version_cardinality_error",

                blockers=[
                    (
                        "selected_version_count:"
                        f"{len(selected_candidates)}"
                    )
                ],

                repository_status=
                    repository_status,

                repository_match_type=
                    repository_match_type,

                repository_score=
                    repository_score,

                repository_candidate_count=
                    len(
                        candidates
                    ),

                version_selection_status=
                    version_selection_status,

                selected_version_ids=
                    selected_version_ids,
            )
        )

    # ========================================================
    # SELECTED CANONICAL PROVISION VERSION
    # ========================================================

    selected_provision = (
        selected_candidates[
            0
        ]
    )

    normalized = (
        normalize_selected_provision(
            selected_provision
        )
    )

    activation_eligible = (
        normalized[
            "activation_eligible"
        ]
    )

    return {
        "legal_basis_ref":
            legal_basis_ref,

        "resolved":
            True,

        "activation_eligible":
            activation_eligible,

        "resolution_state":
            (
                "resolved_verified"
                if activation_eligible
                else "resolved_not_verified"
            ),

        "parsed":
            parsed,

        "repository_status":
            repository_status,

        "repository_match_type":
            repository_match_type,

        "repository_score":
            repository_score,

        "repository_candidate_count":
            len(
                candidates
            ),

        "version_selection_status":
            version_selection_status,

        "selected_provision_version_ids":
            selected_version_ids,

        "selected_provision":
            normalized,

        "activation_blockers":
            list(
                normalized[
                    "activation_blockers"
                ]
            ),

        "error":
            None,
    }


# ============================================================
# RESOLVE RULE
# ============================================================

def resolve_rule_legal_basis(
    rule,
    manifest,
    temporal_mode=DEFAULT_TEMPORAL_MODE,
    query_date=None,
):

    legal_basis_refs = (
        rule.get(
            "legal_basis_refs",
            []
        )
    )

    resolutions = []

    for legal_basis_ref in legal_basis_refs:

        resolutions.append(
            resolve_legal_basis(
                legal_basis_ref=
                    legal_basis_ref,

                manifest=
                    manifest,

                temporal_mode=
                    temporal_mode,

                query_date=
                    query_date,
            )
        )

    all_resolved = (
        bool(
            resolutions
        )
        and all(
            item[
                "resolved"
            ]
            for item in resolutions
        )
    )

    all_basis_verified = (
        bool(
            resolutions
        )
        and all(
            item[
                "activation_eligible"
            ]
            for item in resolutions
        )
    )

    unresolved_refs = [
        item[
            "legal_basis_ref"
        ]
        for item in resolutions
        if not item[
            "resolved"
        ]
    ]

    activation_blocked_refs = [
        item[
            "legal_basis_ref"
        ]
        for item in resolutions
        if not item[
            "activation_eligible"
        ]
    ]

    return {
        "rule_id":
            rule.get(
                "rule_id"
            ),

        "rule_version":
            rule.get(
                "rule_version"
            ),

        "rule_status":
            rule.get(
                "status"
            ),

        "calculation_enabled":
            rule.get(
                "calculation_enabled"
            ),

        "temporal_mode":
            temporal_mode,

        "query_date":
            query_date,

        "legal_basis_count":
            len(
                legal_basis_refs
            ),

        "resolved_count":
            sum(
                1
                for item in resolutions
                if item[
                    "resolved"
                ]
            ),

        "unresolved_count":
            sum(
                1
                for item in resolutions
                if not item[
                    "resolved"
                ]
            ),

        "activation_ready_basis_count":
            sum(
                1
                for item in resolutions
                if item[
                    "activation_eligible"
                ]
            ),

        "all_resolved":
            all_resolved,

        "all_basis_verified":
            all_basis_verified,

        "activation_eligible":
            (
                all_resolved
                and all_basis_verified
                and len(
                    legal_basis_refs
                ) > 0
            ),

        "unresolved_refs":
            unresolved_refs,

        "activation_blocked_refs":
            activation_blocked_refs,

        "resolutions":
            resolutions,
    }


# ============================================================
# RESOLVE RULESET
# ============================================================

def resolve_ruleset_legal_basis(
    ruleset_path,
    manifest_path=None,
    temporal_mode=DEFAULT_TEMPORAL_MODE,
    query_date=None,
):

    validate_temporal_input(
        temporal_mode,
        query_date,
    )

    ruleset_path = Path(
        ruleset_path
    )

    validation = (
        validate_deadline_rules(
            ruleset_path=
                ruleset_path,

            raise_on_error=
                True,
        )
    )

    if not validation[
        "valid"
    ]:

        raise DeadlineLegalBasisResolverError(
            "Deadline Rule Registry geçerli değil."
        )

    ruleset = load_json(
        ruleset_path
    )

    if manifest_path is None:

        manifest_path = (
            discover_manifest_path()
        )

    else:

        manifest_path = Path(
            manifest_path
        )

    manifest = (
        provision_repo
        .load_provisions_manifest(
            manifest_path
        )
    )

    enabled_provisions = (
        provision_repo
        .get_enabled_provisions(
            manifest
        )
    )

    rule_results = []

    for rule in ruleset.get(
        "rules",
        []
    ):

        rule_results.append(
            resolve_rule_legal_basis(
                rule=
                    rule,

                manifest=
                    manifest,

                temporal_mode=
                    temporal_mode,

                query_date=
                    query_date,
            )
        )

    return {
        "resolver_version":
            DEADLINE_LEGAL_BASIS_RESOLVER_VERSION,

        "ruleset_id":
            ruleset.get(
                "ruleset_id"
            ),

        "ruleset_path":
            str(
                ruleset_path
            ),

        "manifest_path":
            str(
                manifest_path
            ),

        "temporal_mode":
            temporal_mode,

        "query_date":
            query_date,

        "enabled_provision_count":
            len(
                enabled_provisions
            ),

        "rule_count":
            len(
                rule_results
            ),

        "fully_resolved_rule_count":
            sum(
                1
                for result in rule_results
                if result[
                    "all_resolved"
                ]
            ),

        "fully_verified_basis_rule_count":
            sum(
                1
                for result in rule_results
                if result[
                    "all_basis_verified"
                ]
            ),

        "activation_eligible_count":
            sum(
                1
                for result in rule_results
                if result[
                    "activation_eligible"
                ]
            ),

        "rules":
            rule_results,
    }


# ============================================================
# SYNTHETIC PROVISION
# ============================================================

def build_synthetic_provision(
    verification_state,
    formal_verified,
    formal_status,
    evidence_verified,
):

    return {
        "provision_id":
            "synthetic_m1_f1",

        "provision_version_id":
            "synthetic_m1_f1_v1",

        "document_id":
            "kanun_9999",

        "enabled":
            True,

        "verification_state":
            verification_state,

        "locator": {
            "madde":
                "1",

            "fikra":
                "1",

            "bent":
                None,
        },

        "formal": {
            "verified":
                formal_verified,

            "status":
                formal_status,

            "valid_from":
                "2000-01-01",

            "valid_through":
                None,

            "repeal_effective_date":
                None,

            "evidence": [
                {
                    "evidence_id":
                        "synthetic_evidence",

                    "kind":
                        "statute_text",

                    "source_document_id":
                        "kanun_9999",

                    "source_url":
                        None,

                    "citation":
                        "Synthetic evidence",

                    "verified":
                        evidence_verified,

                    "notes":
                        None,
                }
            ],
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
            "Synthetic test provision.",
    }


# ============================================================
# SELF TEST
# ============================================================

def run_self_test():

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - DEADLINE LEGAL BASIS RESOLVER V1.2"
    )

    print(
        "======================================"
    )

    # ========================================================
    # T01 REPOSITORY API
    # ========================================================

    for function_name in [
        "load_provisions_manifest",
        "get_enabled_provisions",
        "get_locator",
        "get_provision_id",
        "get_provision_version_id",
        "resolve_provisions",
    ]:

        assert hasattr(
            provision_repo,
            function_name,
        )

        assert callable(
            getattr(
                provision_repo,
                function_name,
            )
        )

    print(
        "T01 Provision Repository API:",
        "PASS"
    )

    # ========================================================
    # T02 VERSION POLICY API
    # ========================================================

    assert hasattr(
        version_policy,
        "select_provision_versions",
    )

    assert callable(
        version_policy
        .select_provision_versions
    )

    print(
        "T02 Provision Version Policy API:",
        "PASS"
    )

    # ========================================================
    # T03 TEMPORAL MODES
    # ========================================================

    for mode in (
        "neutral",
        "historical_date",
        "current",
    ):

        assert mode in (
            version_policy
            .VALID_TEMPORAL_MODES
        )

    print(
        "T03 Temporal modes:",
        "PASS"
    )

    # ========================================================
    # T04 PARSER
    # ========================================================

    parsed = (
        parse_legal_basis_ref(
            "IYUK_2577_m7_2_b"
        )
    )

    assert parsed[
        "valid"
    ]

    assert (
        parsed[
            "document_id"
        ]
        == "kanun_2577"
    )

    assert (
        parsed[
            "madde"
        ]
        == "7"
    )

    assert (
        parsed[
            "fikra"
        ]
        == "2"
    )

    assert (
        parsed[
            "bent"
        ]
        == "b"
    )

    print(
        "T04 Legal basis parser:",
        "PASS"
    )

    # ========================================================
    # T05 INVALID REFERENCE
    # ========================================================

    parsed = (
        parse_legal_basis_ref(
            "invalid_reference"
        )
    )

    assert (
        parsed[
            "valid"
        ]
        is False
    )

    print(
        "T05 Invalid reference blocked:",
        "PASS"
    )

    # ========================================================
    # T06 HISTORICAL DATE GUARD
    # ========================================================

    historical_guard_passed = False

    try:

        validate_temporal_input(
            "historical_date",
            None,
        )

    except DeadlineLegalBasisResolverError:

        historical_guard_passed = True

    assert historical_guard_passed

    print(
        "T06 Historical query date guard:",
        "PASS"
    )

    # ========================================================
    # T07 PARTIAL VERIFICATION BLOCK
    # ========================================================

    synthetic = (
        build_synthetic_provision(
            verification_state=
                "partially_verified",

            formal_verified=
                True,

            formal_status=
                "active",

            evidence_verified=
                True,
        )
    )

    safety = (
        evaluate_provision_activation(
            synthetic
        )
    )

    assert (
        safety[
            "activation_eligible"
        ]
        is False
    )

    print(
        "T07 Partial verification blocked:",
        "PASS"
    )

    # ========================================================
    # T08 FULL VERIFICATION
    # ========================================================

    synthetic = (
        build_synthetic_provision(
            verification_state=
                "verified",

            formal_verified=
                True,

            formal_status=
                "active",

            evidence_verified=
                True,
        )
    )

    safety = (
        evaluate_provision_activation(
            synthetic
        )
    )

    assert (
        safety[
            "activation_eligible"
        ]
        is True
    )

    print(
        "T08 Fully verified provision allowed:",
        "PASS"
    )

    # ========================================================
    # T09 RULESET VALIDATION
    # ========================================================

    validation = (
        validate_deadline_rules(
            DEFAULT_RULESET_PATH
        )
    )

    assert (
        validation[
            "valid"
        ]
        is True
    )

    print(
        "T09 Production ruleset validation:",
        "PASS"
    )

    # ========================================================
    # T10 MANIFEST DISCOVERY
    # ========================================================

    manifest_path = (
        discover_manifest_path()
    )

    manifest = (
        provision_repo
        .load_provisions_manifest(
            manifest_path
        )
    )

    assert manifest_path.exists()

    print(
        "T10 Provision manifest discovery:",
        "PASS"
    )

    # ========================================================
    # T11 REAL REPOSITORY WRAPPER
    # ========================================================

    raw = (
        provision_repo
        .resolve_provisions(
            "kanun_2577",
            "7",
            "1",
            None,
            manifest,
        )
    )

    assert isinstance(
        raw,
        dict,
    )

    assert (
        raw.get(
            "status"
        )
        == "resolved"
    )

    assert (
        isinstance(
            raw.get(
                "candidates"
            ),
            list,
        )
    )

    assert (
        len(
            raw[
                "candidates"
            ]
        )
        >= 1
    )

    print(
        "T11 Repository wrapper handling:",
        "PASS"
    )

    # ========================================================
    # T12 REAL VERSION SELECTION
    # ========================================================

    version_result = (
        version_policy
        .select_provision_versions(
            candidates=
                raw[
                    "candidates"
                ],

            temporal_mode=
                "current",

            query_date=
                None,
        )
    )

    assert (
        version_result.get(
            "selection_status"
        )
        == "selected"
    )

    assert (
        len(
            version_result.get(
                "selected_candidates",
                [],
            )
        )
        == 1
    )

    print(
        "T12 Current version selected:",
        "PASS"
    )

    # ========================================================
    # T13 REAL IYUK RESOLUTION
    # ========================================================

    iyuk_result = (
        resolve_legal_basis(
            legal_basis_ref=
                "IYUK_2577_m7_1",

            manifest=
                manifest,

            temporal_mode=
                "current",
        )
    )

    assert (
        iyuk_result[
            "resolved"
        ]
        is True
    )

    assert (
        iyuk_result[
            "resolution_state"
        ]
        == "resolved_verified"
    )

    assert (
        iyuk_result[
            "activation_eligible"
        ]
        is True
    )

    print(
        "T13 Real IYUK verified resolution:",
        "PASS"
    )

    # ========================================================
    # T14 NEUTRAL FAIL CLOSED
    # ========================================================

    neutral_result = (
        resolve_legal_basis(
            legal_basis_ref=
                "IYUK_2577_m7_1",

            manifest=
                manifest,

            temporal_mode=
                "neutral",
        )
    )

    assert (
        neutral_result[
            "activation_eligible"
        ]
        is False
    )

    assert (
        neutral_result[
            "resolution_state"
        ]
        == "version_selection_neutral"
    )

    print(
        "T14 Neutral activation fail-closed:",
        "PASS"
    )

    # ========================================================
    # T15 PRODUCTION RULE
    # ========================================================

    result = (
        resolve_ruleset_legal_basis(
            ruleset_path=
                DEFAULT_RULESET_PATH,

            manifest_path=
                manifest_path,

            temporal_mode=
                "current",
        )
    )

    assert (
        result[
            "rule_count"
        ]
        >= 1
    )

    print(
        "T15 Production rule resolution:",
        "PASS"
    )

    print()

    print(
        "Manifest:",
        result[
            "manifest_path"
        ],
    )

    print(
        "Temporal mode:",
        result[
            "temporal_mode"
        ],
    )

    print(
        "Enabled provision:",
        result[
            "enabled_provision_count"
        ],
    )

    print(
        "Rule:",
        result[
            "rule_count"
        ],
    )

    print(
        "Fully resolved rule:",
        result[
            "fully_resolved_rule_count"
        ],
    )

    print(
        "Fully verified basis rule:",
        result[
            "fully_verified_basis_rule_count"
        ],
    )

    print(
        "Activation eligible:",
        result[
            "activation_eligible_count"
        ],
    )

    print()

    for rule_result in result[
        "rules"
    ]:

        print(
            "Rule:",
            rule_result[
                "rule_id"
            ],
        )

        for resolution in rule_result[
            "resolutions"
        ]:

            print(
                "-",
                resolution[
                    "legal_basis_ref"
                ],
                "->",
                resolution[
                    "resolution_state"
                ],
                "| repo=",
                resolution[
                    "repository_status"
                ],
                "| version=",
                resolution[
                    "version_selection_status"
                ],
                "| activation=",
                resolution[
                    "activation_eligible"
                ],
            )

    print()

    print(
        "======================================"
    )

    print(
        " DEADLINE LEGAL BASIS RESOLVER V1.2: 15/15 PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Vergi AI Deadline Legal Basis Resolver V1.2"
        )
    )

    parser.add_argument(
        "--ruleset",
        dest="ruleset_path",
        default=str(
            DEFAULT_RULESET_PATH
        ),
    )

    parser.add_argument(
        "--manifest",
        dest="manifest_path",
        default=None,
    )

    parser.add_argument(
        "--temporal-mode",
        dest="temporal_mode",
        choices=sorted(
            SUPPORTED_TEMPORAL_MODES
        ),
        default=
            DEFAULT_TEMPORAL_MODE,
    )

    parser.add_argument(
        "--query-date",
        dest="query_date",
        default=None,
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
        dest="self_test",
    )

    args = parser.parse_args()

    if args.self_test:

        run_self_test()

        return

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - DEADLINE LEGAL BASIS RESOLVER V1.2"
    )

    print(
        "======================================"
    )

    try:

        result = (
            resolve_ruleset_legal_basis(
                ruleset_path=
                    Path(
                        args.ruleset_path
                    ),

                manifest_path=
                    (
                        Path(
                            args.manifest_path
                        )
                        if args.manifest_path
                        else None
                    ),

                temporal_mode=
                    args.temporal_mode,

                query_date=
                    args.query_date,
            )
        )

    except Exception as error:

        print()

        print(
            "LEGAL BASIS RESOLUTION FAILED"
        )

        print(
            error
        )

        print()

        print(
            "======================================"
        )

        print(
            " DEADLINE LEGAL BASIS RESOLVER V1.2: FAIL"
        )

        print(
            "======================================"
        )

        sys.exit(
            1
        )

    print()

    print(
        "Ruleset:",
        result[
            "ruleset_id"
        ],
    )

    print(
        "Manifest:",
        result[
            "manifest_path"
        ],
    )

    print(
        "Temporal mode:",
        result[
            "temporal_mode"
        ],
    )

    print(
        "Query date:",
        result[
            "query_date"
        ],
    )

    print(
        "Enabled provision:",
        result[
            "enabled_provision_count"
        ],
    )

    print(
        "Rule:",
        result[
            "rule_count"
        ],
    )

    print(
        "Fully resolved:",
        result[
            "fully_resolved_rule_count"
        ],
    )

    print(
        "Fully verified basis:",
        result[
            "fully_verified_basis_rule_count"
        ],
    )

    print(
        "Activation eligible:",
        result[
            "activation_eligible_count"
        ],
    )

    print()

    for rule_result in result[
        "rules"
    ]:

        print(
            "Rule:",
            rule_result[
                "rule_id"
            ],
        )

        print(
            "Status:",
            rule_result[
                "rule_status"
            ],
        )

        print(
            "All legal basis resolved:",
            rule_result[
                "all_resolved"
            ],
        )

        print(
            "All basis verified:",
            rule_result[
                "all_basis_verified"
            ],
        )

        print(
            "Activation eligible:",
            rule_result[
                "activation_eligible"
            ],
        )

        for resolution in rule_result[
            "resolutions"
        ]:

            print(
                "-",
                resolution[
                    "legal_basis_ref"
                ],
                "->",
                resolution[
                    "resolution_state"
                ],
            )

            print(
                "  repository:",
                resolution[
                    "repository_status"
                ],
                "|",
                resolution[
                    "repository_match_type"
                ],
                "| score=",
                resolution[
                    "repository_score"
                ],
            )

            print(
                "  version:",
                resolution[
                    "version_selection_status"
                ],
                "| selected=",
                resolution[
                    "selected_provision_version_ids"
                ],
            )

            print(
                "  activation:",
                resolution[
                    "activation_eligible"
                ],
            )

            if resolution[
                "activation_blockers"
            ]:

                print(
                    "  blockers:",
                    resolution[
                        "activation_blockers"
                    ],
                )

        print()

    print(
        "======================================"
    )

    print(
        " DEADLINE LEGAL BASIS RESOLVER V1.2: PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    main()