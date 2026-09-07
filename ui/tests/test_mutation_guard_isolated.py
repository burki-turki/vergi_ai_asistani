# ============================================================
# Row 19C-1 / ROW 19C-2a - isolated tests for src/mutation_guard.py.
#
# Pure logic only - no database, no filesystem mutation, no network.
# Proves: canonical-serialization determinism, the idempotency-key vs
# request-fingerprint distinction (same key/different fingerprint on a
# target_state change; identical key+fingerprint on a true replay),
# fail-closed validation, and - by construction, via a field-set
# check - that no free-text/secret-shaped field exists on
# MutationIntent for a fingerprint (or an error message) to leak.
#
# ROW 19C-2a IDEMPOTENCY AND CONCURRENCY FINAL CORRECTION: also proves
# the fix for the real race found during the first production writer
# integration - `pre_hash` (authoritative, lock-held filesystem
# evidence) must NEVER be part of either digest, only `pre_revision`
# (the request's own claimed/expected pre-state) may be. See section 3b
# below and src/mutation_guard.py's own module-header explanation.
#
# Run: python -m ui.tests.test_mutation_guard_isolated
# ============================================================

import dataclasses
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import mutation_guard as mg  # noqa: E402

passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label} {detail}")


def expect_raises(exc_type, fn, label, detail=""):
    try:
        fn()
    except exc_type:
        check(label, True)
    except Exception as error:
        check(label, False, f"{detail} - unexpected exception: {error!r}")
    else:
        check(label, False, f"{detail} - no exception raised")


def make_intent(**overrides):
    base = dict(
        actor_type="iam_user",
        actor_ref="42",
        resource_key="case:case_0001",
        action_family="evidence.layer_a_promote",
        target_ref="data/cases/case_0001/evidence/evidence.json",
        target_state=None,
        pre_hash=None,
        pre_revision=None,
    )
    base.update(overrides)
    return mg.MutationIntent(**base)


# ----------------------------------------------------------------
# 1) Field-set closure - by construction, no free-text/secret field.
# ----------------------------------------------------------------

_intent_fields = {f.name for f in dataclasses.fields(mg.MutationIntent)}
_forbidden_field_names = {"raw_request", "request_body", "note", "text", "token", "cookie", "secret", "password"}
check(
    "MutationIntent's field set contains no free-text/secret-shaped field name",
    _intent_fields.isdisjoint(_forbidden_field_names),
    f"fields={_intent_fields}",
)
check(
    "MutationIntent's field set is exactly the documented 8 fields",
    _intent_fields == {
        "actor_type", "actor_ref", "resource_key", "action_family",
        "target_ref", "target_state", "pre_hash", "pre_revision",
    },
    f"got {_intent_fields}",
)

# ----------------------------------------------------------------
# 2) Determinism.
# ----------------------------------------------------------------

intent_a = make_intent()
intent_b = make_intent()  # structurally identical, separately constructed
check(
    "identical intents produce identical idempotency_key",
    mg.compute_idempotency_key(intent_a) == mg.compute_idempotency_key(intent_b),
)
check(
    "identical intents produce identical request_fingerprint",
    mg.compute_request_fingerprint(intent_a) == mg.compute_request_fingerprint(intent_b),
)
check(
    "idempotency_key and request_fingerprint are hex sha256 digests (64 hex chars)",
    len(mg.compute_idempotency_key(intent_a)) == 64
    and all(c in "0123456789abcdef" for c in mg.compute_idempotency_key(intent_a)),
)

# ----------------------------------------------------------------
# 3) The key vs fingerprint distinction - the whole point of having
#    two digests.
# ----------------------------------------------------------------

intent_confirm = make_intent(target_state="confirmed")
intent_reject = make_intent(target_state="rejected")

check(
    "same operation slot, different target_state -> SAME idempotency_key",
    mg.compute_idempotency_key(intent_confirm) == mg.compute_idempotency_key(intent_reject),
)
check(
    "same operation slot, different target_state -> DIFFERENT request_fingerprint",
    mg.compute_request_fingerprint(intent_confirm) != mg.compute_request_fingerprint(intent_reject),
)
check(
    "a true replay (same target_state too) -> SAME idempotency_key AND SAME fingerprint",
    mg.compute_idempotency_key(intent_confirm) == mg.compute_idempotency_key(make_intent(target_state="confirmed"))
    and mg.compute_request_fingerprint(intent_confirm) == mg.compute_request_fingerprint(make_intent(target_state="confirmed")),
)

intent_different_actor = make_intent(actor_ref="99")
check(
    "a different actor_ref changes BOTH idempotency_key and request_fingerprint",
    mg.compute_idempotency_key(intent_a) != mg.compute_idempotency_key(intent_different_actor)
    and mg.compute_request_fingerprint(intent_a) != mg.compute_request_fingerprint(intent_different_actor),
)

intent_different_prehash_and_revision = make_intent(pre_hash="a" * 64, pre_revision="rev-1")
check(
    "a different pre_hash TOGETHER WITH a different pre_revision changes BOTH digests "
    "(because pre_revision changed, not because pre_hash did - see 3b below)",
    mg.compute_idempotency_key(intent_a) != mg.compute_idempotency_key(intent_different_prehash_and_revision)
    and mg.compute_request_fingerprint(intent_a) != mg.compute_request_fingerprint(intent_different_prehash_and_revision),
)

# ----------------------------------------------------------------
# 3b) ROW 19C-2a CORE FIX: `pre_hash` ALONE (same actor/resource/
#     action_family/target_ref/target_state/pre_revision) must NEVER
#     change either digest - this is the exact defect that let a
#     concurrent duplicate request's writer run a second time, because
#     a lock-held re-read of `pre_hash` legitimately differs between
#     two callers of "the same" request purely due to scheduling.
#     `pre_revision` is unaffected by this fix and stays part of
#     identity - covered separately by 3a above.
# ----------------------------------------------------------------

intent_same_revision_hash_a = make_intent(pre_revision="rev-1", pre_hash="a" * 64)
intent_same_revision_hash_b = make_intent(pre_revision="rev-1", pre_hash="b" * 64)  # ONLY pre_hash differs
check(
    "ROW 19C-2a: pre_hash ALONE (same pre_revision) does NOT change idempotency_key "
    "(pre_hash is filesystem evidence, not request identity)",
    mg.compute_idempotency_key(intent_same_revision_hash_a) == mg.compute_idempotency_key(intent_same_revision_hash_b),
)
check(
    "ROW 19C-2a: pre_hash ALONE (same pre_revision) does NOT change request_fingerprint either",
    mg.compute_request_fingerprint(intent_same_revision_hash_a) == mg.compute_request_fingerprint(intent_same_revision_hash_b),
)
check(
    "ROW 19C-2a: pre_hash is absent from _identity_fields()'s own output",
    "pre_hash" not in mg._identity_fields(intent_same_revision_hash_a),
)
check(
    "ROW 19C-2a: pre_revision alone (same pre_hash) DOES change idempotency_key "
    "(pre_revision is request identity, unaffected by this fix)",
    mg.compute_idempotency_key(make_intent(pre_revision="rev-1", pre_hash="a" * 64))
    != mg.compute_idempotency_key(make_intent(pre_revision="rev-2", pre_hash="a" * 64)),
)

# ----------------------------------------------------------------
# 4) Fail-closed validation.
# ----------------------------------------------------------------

expect_raises(
    mg.InvalidMutationIntentError,
    lambda: mg.validate_intent(make_intent(actor_type="not_a_real_actor_type")),
    "unknown actor_type is rejected",
)
expect_raises(
    mg.InvalidMutationIntentError,
    lambda: mg.validate_intent(make_intent(actor_ref="")),
    "empty actor_ref is rejected",
)
expect_raises(
    mg.InvalidMutationIntentError,
    lambda: mg.validate_intent(make_intent(resource_key="")),
    "empty resource_key is rejected",
)
expect_raises(
    mg.InvalidMutationIntentError,
    lambda: mg.validate_intent(make_intent(pre_hash="only-hash-no-revision", pre_revision=None)),
    "half-specified pre-state (hash without revision) is rejected",
)
expect_raises(
    mg.InvalidMutationIntentError,
    lambda: mg.validate_intent(make_intent(pre_hash=None, pre_revision="only-revision-no-hash")),
    "half-specified pre-state (revision without hash) is rejected",
)
expect_raises(
    mg.InvalidMutationIntentError,
    lambda: mg.validate_intent("not-an-intent"),
    "a non-MutationIntent value is rejected",
)
check(
    "both pre_hash and pre_revision None (first write) is VALID, not rejected",
    mg.validate_intent(make_intent(pre_hash=None, pre_revision=None)) is None,
)

expect_raises(
    mg.InvalidMutationIntentError,
    lambda: mg.compute_idempotency_key(make_intent(actor_ref="")),
    "compute_idempotency_key itself validates before hashing (fail-closed, not just validate_intent)",
)
expect_raises(
    mg.InvalidMutationIntentError,
    lambda: mg.compute_request_fingerprint(make_intent(actor_ref="")),
    "compute_request_fingerprint itself validates before hashing (fail-closed, not just validate_intent)",
)

# ----------------------------------------------------------------
# 5) FAILURE_CODES / RESOLUTION_CODES stay closed, disjoint
#    vocabularies (mirrors iam.security_events.reason_code's own
#    closed-enum convention, not free text).
# ----------------------------------------------------------------

check(
    "FAILURE_CODES and RESOLUTION_CODES are disjoint (no code means two different things)",
    mg.FAILURE_CODES.isdisjoint(mg.RESOLUTION_CODES),
)
check(
    "FAILURE_CODES is non-empty and every entry is a non-empty string",
    len(mg.FAILURE_CODES) > 0 and all(isinstance(c, str) and c for c in mg.FAILURE_CODES),
)
check(
    "RESOLUTION_CODES is non-empty and every entry is a non-empty string",
    len(mg.RESOLUTION_CODES) > 0 and all(isinstance(c, str) and c for c in mg.RESOLUTION_CODES),
)

print(f"--- test_mutation_guard_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
