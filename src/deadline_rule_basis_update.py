# ============================================================
# VERGİ AI - DEADLINE RULE LEGAL BASIS UPDATE V1
#
# AMAÇ
# ----
#
# Aktif:
#
#   iyuk_tax_court_general_lawsuit_filing
#
# deadline rule'una:
#
#   IYUK_2577_m61_1
#
# hukuki dayanağını kontrollü biçimde eklemek.
#
#
# NEDEN?
# ------
#
# İYUK m.8/3 çalışmaya ara verme dönemine rastlayan
# deadline için uzama kuralını düzenler.
#
# Bu dönemin ve ilgili istisnaların canonical dayanağı
# İYUK m.61/1 provision'ıdır.
#
#
# GÜVENLİK
# --------
#
# - Varsayılan REVIEW modudur.
# - Mutation yalnız --approve ile yapılır.
# - Production registry önceden validate edilir.
# - Rule active kalmalıdır.
# - calculation_enabled=True korunmalıdır.
# - requires_human_review=True korunmalıdır.
# - Candidate ruleset schema/semantic validator'dan geçer.
# - Candidate legal basis resolver'dan 6/6 verified geçmelidir.
# - Backup alınır.
# - Atomic write yapılır.
# - Post-write validation yapılır.
# - Hata halinde rollback uygulanır.
# - Audit kaydı oluşturulur.
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

UPDATE_VERSION = "1"


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

TARGET_BASIS_REF = (
    "IYUK_2577_m61_1"
)

EXPECTED_BASIS_COUNT_AFTER = 6


# ============================================================
# CURRENT NOTES
# ============================================================

UPDATED_NOTES = (
    "İYUK m.7/1, m.7/2-b, m.8 ve m.61/1 esas alınarak "
    "oluşturulmuş genel vergi mahkemesi dava açma süresi "
    "kuralıdır. Hukuki dayanaklar Legal Knowledge Engine "
    "üzerinden canonical ve verified provision version'lara "
    "bağlanmıştır. Özel kanunda farklı süre bulunması, somut "
    "anchor event'in doğrulama durumu ve çalışmaya ara verme "
    "uygulanabilirliği ayrıca deterministik policy katmanları "
    "tarafından değerlendirilmelidir."
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
            + ".before_m61_basis_"
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
# FIND RULE
# ============================================================

def find_target_rule(
    ruleset,
):

    rules = ruleset.get(
        "rules",
        []
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
            "Target rule tam olarak bir kez bulunmalı.\n"
            f"Bulunan: {len(matches)}"
        )

    return matches[
        0
    ]


# ============================================================
# REGISTRY VALIDATION
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

    if result.get(
        "valid"
    ) is not True:

        raise RuntimeError(
            "Deadline Rule Registry valid değil."
        )

    return result


# ============================================================
# CURRENT RULE SAFETY
# ============================================================

def validate_current_rule_state(
    rule,
):

    blockers = []

    if (
        rule.get(
            "status"
        )
        != "active"
    ):

        blockers.append(
            "rule_status_not_active"
        )

    if (
        rule.get(
            "calculation_enabled"
        )
        is not True
    ):

        blockers.append(
            "calculation_enabled_not_true"
        )

    if (
        rule.get(
            "requires_human_review"
        )
        is not True
    ):

        blockers.append(
            "requires_human_review_not_true"
        )

    legal_basis_refs = (
        rule.get(
            "legal_basis_refs",
            []
        )
    )

    if not isinstance(
        legal_basis_refs,
        list,
    ):

        blockers.append(
            "legal_basis_refs_not_list"
        )

    if blockers:

        raise RuntimeError(
            "Current active rule safety FAIL:\n- "
            + "\n- ".join(
                blockers
            )
        )


# ============================================================
# BUILD CANDIDATE
# ============================================================

def build_candidate_ruleset(
    ruleset,
):

    candidate = json.loads(
        json.dumps(
            ruleset,
            ensure_ascii=False,
        )
    )

    rule = find_target_rule(
        candidate
    )

    legal_basis_refs = rule.get(
        "legal_basis_refs",
        []
    )

    if TARGET_BASIS_REF not in legal_basis_refs:

        legal_basis_refs.append(
            TARGET_BASIS_REF
        )

    rule[
        "legal_basis_refs"
    ] = legal_basis_refs

    rule[
        "notes"
    ] = UPDATED_NOTES

    # --------------------------------------------------------
    # Lifecycle safety
    # --------------------------------------------------------

    rule[
        "status"
    ] = "active"

    rule[
        "calculation_enabled"
    ] = True

    rule[
        "requires_human_review"
    ] = True

    return candidate


# ============================================================
# TEMP CANDIDATE PATH
# ============================================================

def candidate_path():

    return (
        RULESET_PATH.parent
        / "deadline_rules.m61_candidate.json"
    )


# ============================================================
# VALIDATE CANDIDATE
# ============================================================

def validate_candidate(
    candidate,
):

    path = candidate_path()

    try:

        atomic_write_json(
            path,
            candidate,
        )

        # ====================================================
        # RULE VALIDATOR
        # ====================================================

        validate_registry(
            path
        )

        # ====================================================
        # LEGAL BASIS RESOLVER
        # ====================================================

        resolver_result = (
            resolve_ruleset_legal_basis(
                ruleset_path=
                    path,

                manifest_path=
                    PROVISIONS_PATH,

                temporal_mode=
                    "current",

                query_date=
                    None,
            )
        )

        matches = [
            result
            for result
            in resolver_result.get(
                "rules",
                []
            )
            if (
                result.get(
                    "rule_id"
                )
                == TARGET_RULE_ID
            )
        ]

        if len(
            matches
        ) != 1:

            raise RuntimeError(
                "Candidate resolver target rule "
                "sonucu tam bir kez bulunmadı."
            )

        target_result = (
            matches[
                0
            ]
        )

        if (
            target_result.get(
                "legal_basis_count"
            )
            != EXPECTED_BASIS_COUNT_AFTER
        ):

            raise RuntimeError(
                "Candidate legal basis count "
                f"{EXPECTED_BASIS_COUNT_AFTER} değil."
            )

        if (
            target_result.get(
                "all_resolved"
            )
            is not True
        ):

            raise RuntimeError(
                "Candidate legal basis tam çözülmedi."
            )

        if (
            target_result.get(
                "all_basis_verified"
            )
            is not True
        ):

            raise RuntimeError(
                "Candidate legal basis tam verified değil."
            )

        if (
            target_result.get(
                "activation_eligible"
            )
            is not True
        ):

            raise RuntimeError(
                "Candidate legal basis activation eligible değil."
            )

        target_resolution = next(
            (
                item
                for item
                in target_result.get(
                    "resolutions",
                    []
                )
                if (
                    item.get(
                        "legal_basis_ref"
                    )
                    == TARGET_BASIS_REF
                )
            ),
            None,
        )

        if target_resolution is None:

            raise RuntimeError(
                "IYUK_2577_m61_1 resolver sonucunda bulunamadı."
            )

        if (
            target_resolution.get(
                "resolution_state"
            )
            != "resolved_verified"
        ):

            raise RuntimeError(
                "IYUK_2577_m61_1 resolved_verified değil."
            )

        return (
            resolver_result,
            target_result,
            target_resolution,
        )

    finally:

        if path.exists():

            path.unlink()


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
            "basis_update_"
            + TARGET_RULE_ID
            + "_"
            + timestamp
            + ".json"
        )
    )

    audit = {
        "audit_type":
            "deadline_rule_legal_basis_update",

        "update_version":
            UPDATE_VERSION,

        "updated_at":
            now.isoformat(),

        "rule_id":
            TARGET_RULE_ID,

        "added_legal_basis_ref":
            TARGET_BASIS_REF,

        "before_ruleset_sha256":
            before_hash,

        "after_ruleset_sha256":
            after_hash,

        "backup_path":
            str(
                backup_path
            ),

        "rule_state": {
            "status":
                "active",

            "calculation_enabled":
                True,

            "requires_human_review":
                True,
        },

        "legal_basis": {
            "resolver_version":
                DEADLINE_LEGAL_BASIS_RESOLVER_VERSION,

            "legal_basis_count":
                legal_basis_result.get(
                    "legal_basis_count"
                ),

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

            "refs": [
                item.get(
                    "legal_basis_ref"
                )
                for item
                in legal_basis_result.get(
                    "resolutions",
                    []
                )
            ],

            "selected_versions": [
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

        "notes":
            (
                "IYUK m.61/1 legal basis aktif deadline rule'a "
                "eklenmiştir. Rule lifecycle değişmemiştir. "
                "Bu audit herhangi bir deadline hesabı değildir."
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
        " VERGİ AI - DEADLINE RULE BASIS UPDATE V1"
    )

    print(
        " MODE: REVIEW"
    )

    print(
        "======================================"
    )

    # ========================================================
    # CURRENT
    # ========================================================

    validate_registry(
        RULESET_PATH
    )

    print(
        "Production registry:",
        "PASS"
    )

    ruleset = load_json(
        RULESET_PATH
    )

    rule = find_target_rule(
        ruleset
    )

    validate_current_rule_state(
        rule
    )

    print(
        "Active rule safety:",
        "PASS"
    )

    current_refs = rule.get(
        "legal_basis_refs",
        []
    )

    # ========================================================
    # ALREADY PRESENT
    # ========================================================

    if (
        TARGET_BASIS_REF
        in current_refs
    ):

        print()

        print(
            TARGET_BASIS_REF,
            "zaten rule içinde mevcut."
        )

        print()

        print(
            "======================================"
        )

        print(
            " DEADLINE RULE BASIS UPDATE V1: ALREADY PRESENT"
        )

        print(
            "======================================"
        )

        return

    # ========================================================
    # CANDIDATE
    # ========================================================

    candidate = (
        build_candidate_ruleset(
            ruleset
        )
    )

    (
        resolver_result,
        legal_basis_result,
        target_resolution,
    ) = validate_candidate(
        candidate
    )

    print(
        "Candidate registry validator:",
        "PASS"
    )

    print(
        "Candidate legal basis resolver:",
        "PASS"
    )

    # ========================================================
    # OUTPUT
    # ========================================================

    print()

    print(
        "Rule ID:",
        TARGET_RULE_ID
    )

    print()

    print(
        "CURRENT LEGAL BASIS COUNT:",
        len(
            current_refs
        )
    )

    for ref in current_refs:

        print(
            "-",
            ref
        )

    print()

    print(
        "ADD:"
    )

    print(
        "-",
        TARGET_BASIS_REF
    )

    print()

    print(
        "PROPOSED LEGAL BASIS COUNT:",
        legal_basis_result[
            "legal_basis_count"
        ]
    )

    print()

    print(
        "NEW BASIS RESOLUTION:"
    )

    print(
        "- state:",
        target_resolution[
            "resolution_state"
        ]
    )

    print(
        "- version:",
        target_resolution[
            "selected_provision_version_ids"
        ]
    )

    print(
        "- activation:",
        target_resolution[
            "activation_eligible"
        ]
    )

    print()

    print(
        "RULE STATE:"
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
        "python src\\deadline_rule_basis_update.py --approve"
    )

    print()

    print(
        "======================================"
    )

    print(
        " DEADLINE RULE BASIS UPDATE V1: READY"
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
        " VERGİ AI - DEADLINE RULE BASIS UPDATE V1"
    )

    print(
        " MODE: APPROVE"
    )

    print(
        "======================================"
    )

    # ========================================================
    # CURRENT STATE
    # ========================================================

    validate_registry(
        RULESET_PATH
    )

    ruleset = load_json(
        RULESET_PATH
    )

    rule = find_target_rule(
        ruleset
    )

    validate_current_rule_state(
        rule
    )

    current_refs = (
        rule.get(
            "legal_basis_refs",
            []
        )
    )

    # ========================================================
    # IDEMPOTENT
    # ========================================================

    if (
        TARGET_BASIS_REF
        in current_refs
    ):

        print()

        print(
            TARGET_BASIS_REF,
            "zaten mevcut."
        )

        print(
            "Değişiklik yapılmadı."
        )

        print()

        print(
            "======================================"
        )

        print(
            " DEADLINE RULE BASIS UPDATE V1: ALREADY PRESENT"
        )

        print(
            "======================================"
        )

        return

    # ========================================================
    # BUILD + VALIDATE CANDIDATE
    # ========================================================

    candidate = (
        build_candidate_ruleset(
            ruleset
        )
    )

    (
        candidate_resolver,
        candidate_basis,
        candidate_target,
    ) = validate_candidate(
        candidate
    )

    # ========================================================
    # HASH / BACKUP
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
            candidate,
        )

        # ====================================================
        # POST REGISTRY VALIDATION
        # ====================================================

        validate_registry(
            RULESET_PATH
        )

        # ====================================================
        # POST STATE
        # ====================================================

        written = load_json(
            RULESET_PATH
        )

        written_rule = find_target_rule(
            written
        )

        validate_current_rule_state(
            written_rule
        )

        written_refs = (
            written_rule.get(
                "legal_basis_refs",
                []
            )
        )

        if (
            TARGET_BASIS_REF
            not in written_refs
        ):

            raise RuntimeError(
                "Post-write IYUK_2577_m61_1 bulunamadı."
            )

        if (
            len(
                written_refs
            )
            != EXPECTED_BASIS_COUNT_AFTER
        ):

            raise RuntimeError(
                "Post-write legal basis count 6 değil."
            )

        # ====================================================
        # POST RESOLVER
        # ====================================================

        post_resolver = (
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

        post_matches = [
            result
            for result
            in post_resolver.get(
                "rules",
                []
            )
            if (
                result.get(
                    "rule_id"
                )
                == TARGET_RULE_ID
            )
        ]

        if len(
            post_matches
        ) != 1:

            raise RuntimeError(
                "Post resolver target rule bulunamadı."
            )

        post_basis = (
            post_matches[
                0
            ]
        )

        if (
            post_basis.get(
                "legal_basis_count"
            )
            != EXPECTED_BASIS_COUNT_AFTER
        ):

            raise RuntimeError(
                "Post resolver legal basis count 6 değil."
            )

        if (
            post_basis.get(
                "all_resolved"
            )
            is not True
        ):

            raise RuntimeError(
                "Post resolver all_resolved False."
            )

        if (
            post_basis.get(
                "all_basis_verified"
            )
            is not True
        ):

            raise RuntimeError(
                "Post resolver all_basis_verified False."
            )

        if (
            post_basis.get(
                "activation_eligible"
            )
            is not True
        ):

            raise RuntimeError(
                "Post resolver activation_eligible False."
            )

    except Exception:

        shutil.copy2(
            backup_path,
            RULESET_PATH,
        )

        print()

        print(
            "UPDATE FAIL"
        )

        print(
            "Rollback uygulandı."
        )

        raise

    # ========================================================
    # HASH / AUDIT
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
        "LEGAL BASIS UPDATED"
    )

    print(
        "Rule ID:",
        TARGET_RULE_ID
    )

    print(
        "Added:",
        TARGET_BASIS_REF
    )

    print()

    print(
        "Rule state:"
    )

    print(
        "- status:",
        written_rule[
            "status"
        ]
    )

    print(
        "- calculation_enabled:",
        written_rule[
            "calculation_enabled"
        ]
    )

    print(
        "- requires_human_review:",
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

    print(
        "- activation eligible:",
        post_basis[
            "activation_eligible"
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
        " DEADLINE RULE BASIS UPDATE V1: PASS"
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
            "Vergi AI Deadline Rule Legal Basis Update V1"
        )
    )

    parser.add_argument(
        "--approve",
        action="store_true",
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
            " DEADLINE RULE BASIS UPDATE V1: FAIL"
        )

        print(
            "======================================"
        )

        sys.exit(
            1
        )