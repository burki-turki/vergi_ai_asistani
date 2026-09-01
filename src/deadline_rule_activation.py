# ============================================================
# VERGİ AI - DEADLINE RULE ACTIVATION V1
#
# AMAÇ
# ----
#
# Hukuki dayanakları canonical Legal Knowledge Engine
# tarafından doğrulanmış bir deadline rule'u:
#
#     draft
#     calculation_enabled=False
#
# durumundan:
#
#     active
#     calculation_enabled=True
#
# durumuna kontrollü olarak geçirmek.
#
#
# GÜVENLİK
# --------
#
# 1. Production Deadline Rule Registry valid olmalı.
#
# 2. Deadline Legal Basis Resolver:
#
#       all_resolved=True
#       all_basis_verified=True
#       activation_eligible=True
#
#    üretmeli.
#
# 3. Rule halen draft olmalı.
#
# 4. calculation_enabled halen False olmalı.
#
# 5. requires_human_review=True korunmalı.
#
# 6. Varsayılan mod REVIEW'dur.
#
# 7. Gerçek mutation yalnız:
#
#       --approve
#
#    ile yapılır.
#
# 8. Backup + atomic write + post validation + rollback.
#
# 9. Audit kaydı oluşturulur.
#
#
# BU KATMAN:
#
# - deadline hesaplamaz
# - anchor doğrulamaz
# - expiry hesaplamaz
# - special-law applicability çözmez
#
# ============================================================


import argparse
import hashlib
import json
import os
import shutil
import sys

from datetime import datetime
from pathlib import Path


from deadline_rule_validator import (
    validate_deadline_rules,
)

from deadline_legal_basis_resolver import (
    DEADLINE_LEGAL_BASIS_RESOLVER_VERSION,
    resolve_ruleset_legal_basis,
)


# ============================================================
# VERSION
# ============================================================

DEADLINE_RULE_ACTIVATION_VERSION = "1"


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

RULESET_PATH = (
    DATA_DIR
    / "deadline_rules"
    / "deadline_rules.json"
)

PROVISIONS_PATH = (
    DATA_DIR
    / "provisions.json"
)

REVIEWS_DIR = (
    DATA_DIR
    / "deadline_rules"
    / "reviews"
)


# ============================================================
# TARGET
# ============================================================

TARGET_RULE_ID = (
    "iyuk_tax_court_general_lawsuit_filing"
)


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
            f"Dosya bulunamadı:\n{path}"
        )

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:

        return json.load(
            file
        )


def atomic_write_json(
    path,
    data,
):

    path = Path(
        path
    )

    temp_path = (
        path.parent
        / (
            path.name
            + ".tmp"
        )
    )

    with open(
        temp_path,
        "w",
        encoding="utf-8",
        newline="\n",
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )

        file.write(
            "\n"
        )

        file.flush()

        os.fsync(
            file.fileno()
        )

    os.replace(
        temp_path,
        path,
    )


# ============================================================
# HASH
# ============================================================

def sha256_file(
    path,
):

    path = Path(
        path
    )

    digest = (
        hashlib.sha256()
    )

    with open(
        path,
        "rb",
    ) as file:

        while True:

            chunk = file.read(
                1024 * 1024
            )

            if not chunk:
                break

            digest.update(
                chunk
            )

    return digest.hexdigest()


# ============================================================
# BACKUP
# ============================================================

def backup_ruleset():

    timestamp = (
        datetime.now()
        .astimezone()
        .strftime(
            "%Y%m%d_%H%M%S"
        )
    )

    backup_path = (
        RULESET_PATH.parent
        / (
            RULESET_PATH.name
            + ".before_activation_"
            + timestamp
            + ".bak"
        )
    )

    shutil.copy2(
        RULESET_PATH,
        backup_path,
    )

    return backup_path


# ============================================================
# TARGET RULE
# ============================================================

def find_target_rule(
    ruleset,
):

    rules = (
        ruleset.get(
            "rules",
            []
        )
    )

    if not isinstance(
        rules,
        list,
    ):

        raise RuntimeError(
            "rules alanı list değil."
        )

    matches = [
        rule
        for rule
        in rules
        if (
            isinstance(
                rule,
                dict,
            )
            and rule.get(
                "rule_id"
            )
            == TARGET_RULE_ID
        )
    ]

    if len(
        matches
    ) != 1:

        raise RuntimeError(
            "Target rule tam olarak "
            "bir kez bulunmalı.\n"
            f"Bulunan: {len(matches)}"
        )

    return matches[
        0
    ]


# ============================================================
# VALIDATE PRODUCTION REGISTRY
# ============================================================

def validate_registry(
    path,
):

    result = (
        validate_deadline_rules(
            ruleset_path=
                Path(
                    path
                ),

            raise_on_error=
                True,
        )
    )

    if not result.get(
        "valid"
    ):

        raise RuntimeError(
            "Deadline Rule Registry geçerli değil."
        )

    return result


# ============================================================
# LEGAL BASIS CHECK
# ============================================================

def resolve_target_legal_basis():

    result = (
        resolve_ruleset_legal_basis(
            ruleset_path=
                RULESET_PATH,

            manifest_path=
                PROVISIONS_PATH,

            temporal_mode=
                "current",

            query_date=
                None,
        )
    )

    matching_rules = [
        rule
        for rule
        in result.get(
            "rules",
            []
        )
        if (
            rule.get(
                "rule_id"
            )
            == TARGET_RULE_ID
        )
    ]

    if len(
        matching_rules
    ) != 1:

        raise RuntimeError(
            "Legal Basis Resolver target rule "
            "sonucunu tam olarak bir kez "
            "döndürmedi."
        )

    target_result = (
        matching_rules[
            0
        ]
    )

    return (
        result,
        target_result,
    )


# ============================================================
# ACTIVATION PRECONDITIONS
# ============================================================

def check_activation_preconditions(
    rule,
    legal_basis_result,
):

    blockers = []

    # ========================================================
    # CURRENT LIFECYCLE
    # ========================================================

    status = (
        rule.get(
            "status"
        )
    )

    calculation_enabled = (
        rule.get(
            "calculation_enabled"
        )
    )

    requires_human_review = (
        rule.get(
            "requires_human_review"
        )
    )

    if (
        status
        != "draft"
    ):

        blockers.append(
            (
                "rule_status_not_draft:"
                f"{status}"
            )
        )

    if (
        calculation_enabled
        is not False
    ):

        blockers.append(
            (
                "calculation_enabled_not_false:"
                f"{calculation_enabled}"
            )
        )

    # ========================================================
    # HUMAN REVIEW MUST REMAIN REQUIRED
    # ========================================================

    if (
        requires_human_review
        is not True
    ):

        blockers.append(
            "requires_human_review_must_be_true"
        )

    # ========================================================
    # LEGAL BASIS
    # ========================================================

    if (
        legal_basis_result.get(
            "all_resolved"
        )
        is not True
    ):

        blockers.append(
            "legal_basis_not_fully_resolved"
        )

    if (
        legal_basis_result.get(
            "all_basis_verified"
        )
        is not True
    ):

        blockers.append(
            "legal_basis_not_fully_verified"
        )

    if (
        legal_basis_result.get(
            "activation_eligible"
        )
        is not True
    ):

        blockers.append(
            "legal_basis_activation_not_eligible"
        )

    # ========================================================
    # AT LEAST ONE BASIS
    # ========================================================

    legal_basis_refs = (
        rule.get(
            "legal_basis_refs",
            []
        )
    )

    if (
        not isinstance(
            legal_basis_refs,
            list,
        )
        or len(
            legal_basis_refs
        ) == 0
    ):

        blockers.append(
            "missing_legal_basis_refs"
        )

    # ========================================================
    # COUNT CONSISTENCY
    # ========================================================

    resolver_count = (
        legal_basis_result.get(
            "legal_basis_count"
        )
    )

    if (
        isinstance(
            legal_basis_refs,
            list,
        )
        and resolver_count
        != len(
            legal_basis_refs
        )
    ):

        blockers.append(
            (
                "legal_basis_count_mismatch:"
                f"rule={len(legal_basis_refs)},"
                f"resolver={resolver_count}"
            )
        )

    return {
        "eligible":
            len(
                blockers
            ) == 0,

        "blockers":
            blockers,
    }


# ============================================================
# ALREADY ACTIVE CHECK
# ============================================================

def check_already_active(
    rule,
    legal_basis_result,
):

    return (
        rule.get(
            "status"
        )
        == "active"

        and rule.get(
            "calculation_enabled"
        )
        is True

        and rule.get(
            "requires_human_review"
        )
        is True

        and legal_basis_result.get(
            "all_resolved"
        )
        is True

        and legal_basis_result.get(
            "all_basis_verified"
        )
        is True

        and legal_basis_result.get(
            "activation_eligible"
        )
        is True
    )


# ============================================================
# BUILD ACTIVATED REGISTRY
# ============================================================

def build_activated_ruleset(
    ruleset,
):

    new_ruleset = (
        json.loads(
            json.dumps(
                ruleset,
                ensure_ascii=False,
            )
        )
    )

    target_rule = (
        find_target_rule(
            new_ruleset
        )
    )

    target_rule[
        "status"
    ] = "active"

    target_rule[
        "calculation_enabled"
    ] = True

    # --------------------------------------------------------
    # Explicit safety:
    # general IYUK rule remains human-review-required.
    # --------------------------------------------------------

    target_rule[
        "requires_human_review"
    ] = True

    return new_ruleset


# ============================================================
# TEMP VALIDATION
# ============================================================

def validate_candidate_ruleset(
    candidate_ruleset,
):

    temp_path = (
        RULESET_PATH.parent
        / "deadline_rules.activation_candidate.json"
    )

    try:

        atomic_write_json(
            temp_path,
            candidate_ruleset,
        )

        result = (
            validate_registry(
                temp_path
            )
        )

        return result

    finally:

        if temp_path.exists():

            temp_path.unlink()


# ============================================================
# AUDIT
# ============================================================

def write_audit(
    before_hash,
    after_hash,
    backup_path,
    legal_basis_result,
):

    REVIEWS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    now = (
        datetime.now()
        .astimezone()
    )

    timestamp = (
        now.strftime(
            "%Y%m%d_%H%M%S"
        )
    )

    audit_path = (
        REVIEWS_DIR
        / (
            "activation_"
            + TARGET_RULE_ID
            + "_"
            + timestamp
            + ".json"
        )
    )

    audit = {
        "audit_type":
            "deadline_rule_activation",

        "activation_version":
            DEADLINE_RULE_ACTIVATION_VERSION,

        "activated_at":
            now.isoformat(),

        "rule_id":
            TARGET_RULE_ID,

        "before": {
            "status":
                "draft",

            "calculation_enabled":
                False,

            "ruleset_sha256":
                before_hash,
        },

        "after": {
            "status":
                "active",

            "calculation_enabled":
                True,

            "requires_human_review":
                True,

            "ruleset_sha256":
                after_hash,
        },

        "legal_basis": {
            "resolver_version":
                DEADLINE_LEGAL_BASIS_RESOLVER_VERSION,

            "all_resolved":
                legal_basis_result.get(
                    "all_resolved"
                ),

            "all_basis_verified":
                legal_basis_result.get(
                    "all_basis_verified"
                ),

            "activation_eligible":
                legal_basis_result.get(
                    "activation_eligible"
                ),

            "legal_basis_count":
                legal_basis_result.get(
                    "legal_basis_count"
                ),

            "legal_basis_refs": [
                item.get(
                    "legal_basis_ref"
                )
                for item
                in legal_basis_result.get(
                    "resolutions",
                    []
                )
            ],

            "selected_provision_version_ids": [
                version_id
                for item
                in legal_basis_result.get(
                    "resolutions",
                    []
                )
                for version_id
                in item.get(
                    "selected_provision_version_ids",
                    []
                )
            ],
        },

        "backup_path":
            str(
                backup_path
            ),

        "notes":
            (
                "Rule activation yalnız lifecycle "
                "ve calculation_enabled durumunu "
                "değiştirir. requires_human_review=True "
                "korunmuştur. Bu kayıt deadline hesabı "
                "veya somut olay doğrulaması değildir."
            ),
    }

    atomic_write_json(
        audit_path,
        audit,
    )

    return audit_path


# ============================================================
# REVIEW
# ============================================================

def run_review():

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - DEADLINE RULE ACTIVATION V1"
    )

    print(
        " MODE: REVIEW"
    )

    print(
        "======================================"
    )

    # ========================================================
    # REGISTRY VALIDATION
    # ========================================================

    registry_validation = (
        validate_registry(
            RULESET_PATH
        )
    )

    print(
        "Production registry:",
        "PASS"
    )

    # ========================================================
    # LOAD
    # ========================================================

    ruleset = (
        load_json(
            RULESET_PATH
        )
    )

    rule = (
        find_target_rule(
            ruleset
        )
    )

    # ========================================================
    # LEGAL BASIS
    # ========================================================

    (
        resolver_result,
        legal_basis_result,
    ) = resolve_target_legal_basis()

    print(
        "Legal basis resolver:",
        "PASS"
    )

    # ========================================================
    # ALREADY ACTIVE
    # ========================================================

    if check_already_active(
        rule,
        legal_basis_result,
    ):

        print()

        print(
            "Rule zaten güvenli şekilde ACTIVE."
        )

        print()

        print(
            "======================================"
        )

        print(
            " DEADLINE RULE ACTIVATION V1: ALREADY ACTIVE"
        )

        print(
            "======================================"
        )

        return

    # ========================================================
    # PRECONDITIONS
    # ========================================================

    preconditions = (
        check_activation_preconditions(
            rule=
                rule,

            legal_basis_result=
                legal_basis_result,
        )
    )

    if not preconditions[
        "eligible"
    ]:

        print()

        print(
            "ACTIVATION BLOCKED"
        )

        for blocker in preconditions[
            "blockers"
        ]:

            print(
                "-",
                blocker
            )

        raise RuntimeError(
            "Activation preconditions sağlanmadı."
        )

    # ========================================================
    # CANDIDATE REGISTRY
    # ========================================================

    candidate_ruleset = (
        build_activated_ruleset(
            ruleset
        )
    )

    candidate_validation = (
        validate_candidate_ruleset(
            candidate_ruleset
        )
    )

    print(
        "Activation candidate validator:",
        "PASS"
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    print()

    print(
        "Rule ID:",
        rule[
            "rule_id"
        ]
    )

    print(
        "Rule version:",
        rule[
            "rule_version"
        ]
    )

    print()

    print(
        "CURRENT:"
    )

    print(
        "- status:",
        rule[
            "status"
        ]
    )

    print(
        "- calculation_enabled:",
        rule[
            "calculation_enabled"
        ]
    )

    print(
        "- requires_human_review:",
        rule[
            "requires_human_review"
        ]
    )

    print()

    print(
        "PROPOSED:"
    )

    print(
        "- status: active"
    )

    print(
        "- calculation_enabled: True"
    )

    print(
        "- requires_human_review: True"
    )

    print()

    print(
        "LEGAL BASIS:"
    )

    print(
        "- count:",
        legal_basis_result[
            "legal_basis_count"
        ]
    )

    print(
        "- all resolved:",
        legal_basis_result[
            "all_resolved"
        ]
    )

    print(
        "- all verified:",
        legal_basis_result[
            "all_basis_verified"
        ]
    )

    print(
        "- activation eligible:",
        legal_basis_result[
            "activation_eligible"
        ]
    )

    print()

    for resolution in legal_basis_result[
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
            "| version=",
            resolution[
                "selected_provision_version_ids"
            ],
        )

    print()

    print(
        "MUTATION:"
    )

    print(
        "- yapılmadı"
    )

    print()

    print(
        "Onay için:"
    )

    print(
        "python src\\deadline_rule_activation.py --approve"
    )

    print()

    print(
        "======================================"
    )

    print(
        " DEADLINE RULE ACTIVATION V1: READY"
    )

    print(
        "======================================"
    )


# ============================================================
# APPROVE
# ============================================================

def run_approve():

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - DEADLINE RULE ACTIVATION V1"
    )

    print(
        " MODE: APPROVE"
    )

    print(
        "======================================"
    )

    # ========================================================
    # PRE VALIDATE
    # ========================================================

    validate_registry(
        RULESET_PATH
    )

    ruleset = (
        load_json(
            RULESET_PATH
        )
    )

    rule = (
        find_target_rule(
            ruleset
        )
    )

    (
        resolver_result,
        legal_basis_result,
    ) = resolve_target_legal_basis()

    # ========================================================
    # ALREADY ACTIVE
    # ========================================================

    if check_already_active(
        rule,
        legal_basis_result,
    ):

        print()

        print(
            "Rule zaten ACTIVE."
        )

        print(
            "Değişiklik yapılmadı."
        )

        print()

        print(
            "======================================"
        )

        print(
            " DEADLINE RULE ACTIVATION V1: ALREADY ACTIVE"
        )

        print(
            "======================================"
        )

        return

    # ========================================================
    # SAFETY
    # ========================================================

    preconditions = (
        check_activation_preconditions(
            rule=
                rule,

            legal_basis_result=
                legal_basis_result,
        )
    )

    if not preconditions[
        "eligible"
    ]:

        raise RuntimeError(
            "Activation blocked:\n- "
            + "\n- ".join(
                preconditions[
                    "blockers"
                ]
            )
        )

    # ========================================================
    # BUILD + PREVALIDATE
    # ========================================================

    candidate_ruleset = (
        build_activated_ruleset(
            ruleset
        )
    )

    validate_candidate_ruleset(
        candidate_ruleset
    )

    # ========================================================
    # HASH + BACKUP
    # ========================================================

    before_hash = (
        sha256_file(
            RULESET_PATH
        )
    )

    backup_path = (
        backup_ruleset()
    )

    print(
        "Backup:",
        backup_path
    )

    # ========================================================
    # WRITE
    # ========================================================

    try:

        atomic_write_json(
            RULESET_PATH,
            candidate_ruleset,
        )

        # ----------------------------------------------------
        # POST RULE VALIDATION
        # ----------------------------------------------------

        post_validation = (
            validate_registry(
                RULESET_PATH
            )
        )

        # ----------------------------------------------------
        # POST STATE
        # ----------------------------------------------------

        written_ruleset = (
            load_json(
                RULESET_PATH
            )
        )

        written_rule = (
            find_target_rule(
                written_ruleset
            )
        )

        if (
            written_rule.get(
                "status"
            )
            != "active"
        ):

            raise RuntimeError(
                "Post-write status active değil."
            )

        if (
            written_rule.get(
                "calculation_enabled"
            )
            is not True
        ):

            raise RuntimeError(
                "Post-write calculation_enabled True değil."
            )

        if (
            written_rule.get(
                "requires_human_review"
            )
            is not True
        ):

            raise RuntimeError(
                "Post-write human review guard kayboldu."
            )

        # ----------------------------------------------------
        # LEGAL BASIS MUST STILL PASS
        # ----------------------------------------------------

        (
            post_resolver,
            post_basis,
        ) = resolve_target_legal_basis()

        if (
            post_basis.get(
                "all_resolved"
            )
            is not True
        ):

            raise RuntimeError(
                "Post-write legal basis unresolved."
            )

        if (
            post_basis.get(
                "all_basis_verified"
            )
            is not True
        ):

            raise RuntimeError(
                "Post-write legal basis verification FAIL."
            )

        if (
            post_basis.get(
                "activation_eligible"
            )
            is not True
        ):

            raise RuntimeError(
                "Post-write legal basis activation eligibility FAIL."
            )

    except Exception:

        shutil.copy2(
            backup_path,
            RULESET_PATH,
        )

        print()

        print(
            "ACTIVATION FAIL"
        )

        print(
            "Rollback uygulandı."
        )

        raise

    # ========================================================
    # HASH + AUDIT
    # ========================================================

    after_hash = (
        sha256_file(
            RULESET_PATH
        )
    )

    audit_path = (
        write_audit(
            before_hash=
                before_hash,

            after_hash=
                after_hash,

            backup_path=
                backup_path,

            legal_basis_result=
                post_basis,
        )
    )

    # ========================================================
    # OUTPUT
    # ========================================================

    print()

    print(
        "RULE ACTIVATED"
    )

    print(
        "Rule ID:",
        TARGET_RULE_ID
    )

    print(
        "Status:",
        written_rule[
            "status"
        ]
    )

    print(
        "Calculation enabled:",
        written_rule[
            "calculation_enabled"
        ]
    )

    print(
        "Requires human review:",
        written_rule[
            "requires_human_review"
        ]
    )

    print()

    print(
        "Legal basis:"
    )

    print(
        "- count:",
        post_basis[
            "legal_basis_count"
        ]
    )

    print(
        "- all resolved:",
        post_basis[
            "all_resolved"
        ]
    )

    print(
        "- all verified:",
        post_basis[
            "all_basis_verified"
        ]
    )

    print()

    print(
        "Before SHA256:",
        before_hash
    )

    print(
        "After SHA256:",
        after_hash
    )

    print()

    print(
        "Audit:",
        audit_path
    )

    print()

    print(
        "======================================"
    )

    print(
        " DEADLINE RULE ACTIVATION V1: PASS"
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
            "Vergi AI Deadline Rule Activation V1"
        )
    )

    parser.add_argument(
        "--approve",
        action="store_true",
        help=(
            "Rule activation mutation işlemini "
            "gerçekleştirir."
        ),
    )

    args = parser.parse_args()

    if args.approve:

        run_approve()

    else:

        run_review()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        print()

        print(
            "ERROR:"
        )

        print(
            error
        )

        print()

        print(
            "======================================"
        )

        print(
            " DEADLINE RULE ACTIVATION V1: FAIL"
        )

        print(
            "======================================"
        )

        sys.exit(
            1
        )