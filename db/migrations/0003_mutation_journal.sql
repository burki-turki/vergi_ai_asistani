-- Row 19C-1 — Mutation Journal (file-write mutation durability /
-- reconciliation registry).
--
-- Depends on 0001_iam_schema.sql (iam.users) and
-- 0002_mutation_resources.sql (mutation.mutation_resources) having
-- already been applied — applies cleanly on top of either a fresh
-- database that just received 0001+0002, or an existing Row 19B
-- database that already has them. Safely re-runnable (IF NOT EXISTS /
-- ON CONFLICT guards throughout), matching 0001/0002's own contract.
--
-- Reuses mutation.mutation_resources as the ONLY resource-key ->
-- advisory-lock-id registry — this migration does NOT create a second
-- one (see ui/services/mutation_lock.py's Row 19B docstring, which
-- already reserved this for Row 19C).

BEGIN;

-- ---------------------------------------------------------------
-- New GLOBAL resource keys, reserved for FUTURE (Row 19C-2+) global
-- production mutators (ingest.py / deadline_rule_activation.py /
-- deadline_rule_basis_update.py / add_iyuk_*.py). Not used by any
-- writer in this turn (Row 19C-1 is infrastructure-only — no
-- production writer is connected to the coordinator yet).
--
-- Case resources (`case:<case_id>`) are deliberately NOT seeded here
-- — case_id is an open-ended, filesystem-discovered value, not a
-- fixed enum; ui/services/mutation_lock.py's
-- acquire_case_lock_session() creates each one on demand, race-safely
-- (INSERT ... ON CONFLICT DO NOTHING, then a fallback SELECT).
-- ---------------------------------------------------------------
INSERT INTO mutation.mutation_resources (resource_key) VALUES
    ('global:rag_index'),
    ('global:deadline_rules'),
    ('global:legal_provisions')
ON CONFLICT (resource_key) DO NOTHING;

-- ---------------------------------------------------------------
-- mutation.mutation_journal — durability/reconciliation ledger for
-- mutations that touch the FILESYSTEM (not just a single Postgres
-- transaction — see ui/services/mutation_lock.py's Row 19B docstring
-- for why the existing IAM mutation path does not need this table:
-- it never leaves one Postgres transaction, so commit/rollback alone
-- is a complete durability story for it).
--
-- Column type provenance (mechanically derived from 0001/0002, not
-- assumed):
--   - resource_key  TEXT, FK into mutation.mutation_resources
--     (TEXT PRIMARY KEY there, per 0002) — an unknown resource_key
--     can never be journaled, mirroring mutation_lock.py's own
--     fail-closed lookup.
--   - actor_user_id BIGINT NULL REFERENCES iam.users(id) — copies
--     iam.security_events' own nullable actor_user_id column (0001)
--     verbatim in shape. NULL is reserved for the approved CLI
--     identity model's non-IAM-user service actors (see actor_label
--     below), never for "unauthenticated" — every writer this table
--     will eventually serve already requires a resolved actor before
--     it may mutate (Row 19B principle, carried forward unchanged).
--
-- idempotency_key / request_fingerprint are both deterministic,
-- canonical hex-SHA256 digests computed in Python by
-- src/mutation_guard.py (see that module for exactly what each one
-- covers and — just as importantly — what it deliberately does not).
-- This migration does not, and must not, reimplement that logic in
-- SQL; it only stores the two resulting strings and enforces
-- uniqueness on idempotency_key UNCONDITIONALLY, across this table's
-- ENTIRE history — see the plain UNIQUE constraint below (Row 19C-1
-- TARGETED CONTRACT REMEDIATION: an earlier draft of this migration
-- used a PARTIAL unique index scoped to non-`failed` rows instead,
-- specifically to let a retry after a `failed` attempt reuse the same
-- idempotency_key with a fresh row — that approach is REJECTED by the
-- approved contract: idempotency_key is a permanent identity for one
-- operation slot's outcome, `failed` included; ui/services/
-- mutation_coordinator.py's `run_mutation()` never creates a second
-- row for an idempotency_key that already has ANY row, terminal or
-- not — a client that wants to retry a failed operation MUST derive a
-- NEW idempotency_key from a genuinely different `MutationIntent`,
-- e.g. a freshly re-read pre_hash/pre_revision).
--
-- No free text, request body, token, cookie or secret is ever a
-- column here — every column is either a fixed/short code, identity/
-- resource/action metadata, a hash/revision string, or a timestamp.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mutation.mutation_journal (
    id                    BIGSERIAL PRIMARY KEY,

    resource_key          TEXT NOT NULL
                           REFERENCES mutation.mutation_resources(resource_key),
    action_family         TEXT NOT NULL,

    actor_user_id         BIGINT NULL REFERENCES iam.users(id),
    actor_label           TEXT NOT NULL,

    target_ref            TEXT NOT NULL,
    target_state          TEXT NULL,

    pre_hash              TEXT NULL,
    pre_revision          TEXT NULL,
    expected_post_hash    TEXT NULL,
    observed_post_hash    TEXT NULL,

    idempotency_key       TEXT NOT NULL,
    request_fingerprint   TEXT NOT NULL,

    -- UNCONDITIONAL uniqueness across the table's entire history — see
    -- this file's own comment above the column list for why this is a
    -- plain table constraint, never a partial index scoped to any
    -- subset of states.
    CONSTRAINT mutation_journal_idempotency_key_uniq UNIQUE (idempotency_key),

    state                 TEXT NOT NULL CHECK (state IN (
        'prepared', 'executing', 'reconciliation_required', 'completed', 'failed'
    )),
    failure_code          TEXT NULL,
    resolution_code       TEXT NULL,

    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    executing_at          TIMESTAMPTZ NULL,
    resolved_at           TIMESTAMPTZ NULL,

    -- resolved_at is set exactly for the two terminal states, and
    -- never for the three unresolved ones — enforced at the DB level
    -- rather than trusted to application code.
    CONSTRAINT mutation_journal_resolved_at_matches_state CHECK (
        (state IN ('completed', 'failed') AND resolved_at IS NOT NULL)
        OR (state IN ('prepared', 'executing', 'reconciliation_required') AND resolved_at IS NULL)
    ),

    -- `completed` is never written on faith alone — either a real
    -- observed post-hash was captured by the coordinator itself, or
    -- reconciliation recorded a fixed resolution_code explaining what
    -- proved completion (domain-validator/audit evidence, not a
    -- freshly-observed hash accepted as authoritative on its own).
    CONSTRAINT mutation_journal_completed_requires_evidence CHECK (
        state <> 'completed'
        OR observed_post_hash IS NOT NULL
        OR resolution_code IS NOT NULL
    ),

    -- ROW 19C-1 RECONCILIATION ATOMICITY REMEDIATION, TIMESTAMP
    -- SEMANTICS CORRECTION: `executing_at` records WHEN THE WRITER WAS
    -- ACTUALLY INVOKED - never a reconciliation bookkeeping timestamp.
    -- A prior version of this constraint required `executing_at IS NOT
    -- NULL` for EVERY non-`prepared` state unconditionally, which
    -- forced ui.services.mutation_registry's reconciliation-of-a-
    -- stuck-`prepared`-row path to fabricate a fake `executing_at` (via
    -- `COALESCE(executing_at, now())`) even when the writer had
    -- PROVABLY never run at all - a legal/security journal must never
    -- record an execution timestamp for an execution that never
    -- happened. This constraint now distinguishes that ONE specific,
    -- narrow case (`failed` + `resolution_code =
    -- 'reconciled_failed_prepared_never_executed'` - the fixed code
    -- ui.services.mutation_registry uses ONLY when resolving a
    -- `prepared`-origin row via a PROVEN-unchanged pre-state, i.e. the
    -- writer boundary was never crossed) from every other case, where
    -- the original NOT NULL requirement still applies exactly as
    -- before:
    --   - `prepared`                          -> executing_at IS NULL
    --   - `failed` + the prepared-never-executed
    --     resolution_code                     -> executing_at IS NULL
    --   - every other state (`executing`,
    --     `reconciliation_required`, `completed`,
    --     and `failed` with any OTHER resolution_code
    --     or NULL resolution_code - i.e. a `failed`
    --     row that DID reach the writer boundary,
    --     or a hand-seeded test row)           -> executing_at IS NOT NULL
    -- ui.services.mutation_coordinator._mark_executing() (sets
    -- executing_at = now() transitioning `prepared` -> `executing`)
    -- and every later coordinator transition are unaffected - they
    -- never touch a `prepared` row directly, so they always fall into
    -- the "every other state" branch, unchanged from before.
    CONSTRAINT mutation_journal_executing_at_matches_state CHECK (
        CASE
            WHEN state = 'prepared' THEN executing_at IS NULL
            WHEN state = 'failed' AND resolution_code = 'reconciled_failed_prepared_never_executed'
                THEN executing_at IS NULL
            ELSE executing_at IS NOT NULL
        END
    ),

    -- The prepared-never-executed resolution_code is a very specific,
    -- narrow claim ("this row's writer was NEVER invoked, and its
    -- pre-state was proven unchanged") - it must never be attachable
    -- to any OTHER state (a `completed`/`executing`/
    -- `reconciliation_required` row claiming this would be a direct
    -- contradiction: those states, by construction, DID cross the
    -- writer boundary) and, redundantly with the constraint above,
    -- must never coexist with a non-NULL executing_at either - this
    -- constraint is independent of, and does not rely on, the CASE
    -- ordering in mutation_journal_executing_at_matches_state above,
    -- so this specific invariant is enforced even if that other
    -- constraint's own logic were ever restructured.
    CONSTRAINT mutation_journal_prepared_never_executed_code_is_exclusive CHECK (
        resolution_code IS DISTINCT FROM 'reconciled_failed_prepared_never_executed'
        OR (state = 'failed' AND executing_at IS NULL)
    )
);

-- Authoritative "is this resource currently gated by an unresolved
-- mutation" check — the hot path run on every coordinator call, right
-- after the session lock is acquired.
CREATE INDEX IF NOT EXISTS mutation_journal_unresolved_idx
    ON mutation.mutation_journal (resource_key)
    WHERE state IN ('prepared', 'executing', 'reconciliation_required');

CREATE INDEX IF NOT EXISTS mutation_journal_resource_state_idx
    ON mutation.mutation_journal (resource_key, state);

CREATE INDEX IF NOT EXISTS mutation_journal_actor_user_id_idx
    ON mutation.mutation_journal (actor_user_id);

COMMIT;
