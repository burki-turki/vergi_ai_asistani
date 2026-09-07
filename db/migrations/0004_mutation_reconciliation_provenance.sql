-- Row 19C-2a — Mutation Reconciliation Provenance (additive-only).
--
-- Depends on 0001_iam_schema.sql, 0002_mutation_resources.sql and
-- 0003_mutation_journal.sql (mutation.mutation_journal) having already
-- been applied. 0003 is IMMUTABLE — this migration ONLY adds two new
-- NULLable columns and their own CHECK constraints to the existing
-- table; it never alters, drops, or renames anything 0003 already
-- defined, and it issues NO UPDATE of any kind against existing rows.
--
-- WHY THIS EXISTS: ui.services.mutation_registry.reconcile_and_apply_
-- journal_entry() is the only code path that ever attaches a
-- resolution_code to a row (see 0003's own column comments) — until
-- now it recorded WHAT was decided but never WHO (or what) decided
-- it. ui/reconciliation_operator.py's `--apply --actor-ref <ref>` path
-- (Row 19C-2a) is the first caller that can supply a real, if purely
-- technical, actor identity for a reconciliation-apply run; these two
-- columns are where that provenance is durably recorded, in the SAME
-- atomic UPDATE reconcile_and_apply_journal_entry() already issues
-- (see ui/services/mutation_registry.py's _apply_outcome_under_lock())
-- — never a second, separate write, and never for the
-- `reconciliation_required` outcome (which leaves resolution_code
-- NULL — nothing was actually resolved, so nothing is attributed).
--
-- ADDITIVE AND IDEMPOTENT, SAFELY RE-RUNNABLE (schema AND data
-- unchanged on a second run — matching 0001/0002/0003's own contract):
--   - `ADD COLUMN IF NOT EXISTS` for both new columns.
--   - each CHECK constraint is added inside a `DO $$ ... $$` block
--     that first checks pg_constraint for an existing constraint of
--     the same name — PostgreSQL 16 has no `ADD CONSTRAINT IF NOT
--     EXISTS` — so re-running this file is a genuine no-op the second
--     time.
--   - deliberately NEVER uses `NOT VALID`: if some already-existing
--     row somehow violated one of these constraints, THE WHOLE
--     MIGRATION FAILS rather than silently grandfathering it in — the
--     only rows that exist before this migration runs have BOTH new
--     columns NULL by construction (the columns did not exist yet),
--     which every constraint below explicitly permits, so a failure
--     here would mean something is genuinely, unexpectedly wrong, not
--     a shape this migration should ever need to tolerate.
--   - explicit fail-closed non-backfill: no UPDATE statement of any
--     kind appears in this file. Every row already resolved
--     (`completed`/`failed`) before this migration runs keeps
--     reconciled_by_actor_type/reconciled_by_actor_ref permanently
--     NULL — this migration does not, and must not, guess or
--     fabricate a provenance actor for history that predates
--     provenance tracking; NULL provenance on an old, already-resolved
--     row is a permanently valid, unremarkable state (see constraint 4
--     below), never an error condition to "fix".

BEGIN;

ALTER TABLE mutation.mutation_journal
    ADD COLUMN IF NOT EXISTS reconciled_by_actor_type TEXT NULL,
    ADD COLUMN IF NOT EXISTS reconciled_by_actor_ref  TEXT NULL;

-- 1) Closed actor-type set — mirrors 0001/0003's own convention of a
--    fixed, closed vocabulary rather than free text (never
--    'iam_user'/'cli_service' plus anything else a caller might
--    invent). NULL (no provenance recorded) is always permitted.
--    Row 19C-2a's own operator CLI hard-codes 'cli_service' for v1;
--    'iam_user' is reserved for a future browser-driven reconciliation
--    UI (Row 19D+ scope) — real OS/service-identity enforcement behind
--    'cli_service' is explicitly deferred to Row 19D; this column only
--    ever records a caller-declared, technical provenance label.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'mutation.mutation_journal'::regclass
          AND conname = 'mutation_journal_reconciled_actor_type_closed_set'
    ) THEN
        ALTER TABLE mutation.mutation_journal
            ADD CONSTRAINT mutation_journal_reconciled_actor_type_closed_set
            CHECK (reconciled_by_actor_type IS NULL OR reconciled_by_actor_type IN ('iam_user', 'cli_service'));
    END IF;
END $$;

-- 2) actor_ref, when present, is non-blank and length-bounded — a
--    technical provenance label (Row 19C-2a's own CLI --actor-ref
--    flag value, or a future IAM user id/label), never free text and
--    never empty/whitespace-only. 255 matches this project's other
--    short-label columns (e.g. 0003's own actor_label TEXT NOT NULL,
--    which carries no explicit bound of its own but is always a short
--    identity string in practice — this is the first column to make
--    that bound explicit and enforced).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'mutation.mutation_journal'::regclass
          AND conname = 'mutation_journal_reconciled_actor_ref_shape'
    ) THEN
        ALTER TABLE mutation.mutation_journal
            ADD CONSTRAINT mutation_journal_reconciled_actor_ref_shape
            CHECK (
                reconciled_by_actor_ref IS NULL
                OR (length(btrim(reconciled_by_actor_ref)) > 0 AND length(reconciled_by_actor_ref) <= 255)
            );
    END IF;
END $$;

-- 3) actor_type/actor_ref are BOTH-or-NEITHER — exactly one of the two
--    being set alone is a half-specified, meaningless provenance claim
--    (mirrors src/mutation_guard.py's own pre_hash/pre_revision
--    both-or-neither validation for the exact same reason).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'mutation.mutation_journal'::regclass
          AND conname = 'mutation_journal_reconciled_actor_both_or_neither'
    ) THEN
        ALTER TABLE mutation.mutation_journal
            ADD CONSTRAINT mutation_journal_reconciled_actor_both_or_neither
            CHECK ((reconciled_by_actor_type IS NULL) = (reconciled_by_actor_ref IS NULL));
    END IF;
END $$;

-- 4) Provenance-completeness pairing: provenance may be recorded ONLY
--    alongside an actual resolution (resolution_code AND resolved_at
--    both set) — a row can never be claimed to have been reconciled by
--    someone while it is still unresolved. The REVERSE is deliberately
--    NOT required: a resolved row need NOT carry provenance — every
--    row resolved before this migration existed, and every row the
--    COORDINATOR itself resolves directly via run_mutation()'s own
--    _mark_completed (which never sets resolution_code at all — see
--    0003's own column comments distinguishing the coordinator's
--    directly-proven completions from a RECONCILED outcome),
--    legitimately has NULL provenance forever, and that is not an
--    incomplete or defective state.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'mutation.mutation_journal'::regclass
          AND conname = 'mutation_journal_reconciled_provenance_implies_resolved'
    ) THEN
        ALTER TABLE mutation.mutation_journal
            ADD CONSTRAINT mutation_journal_reconciled_provenance_implies_resolved
            CHECK (
                (reconciled_by_actor_type IS NULL AND reconciled_by_actor_ref IS NULL)
                OR (resolution_code IS NOT NULL AND resolved_at IS NOT NULL)
            );
    END IF;
END $$;

COMMIT;
