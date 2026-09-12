-- RAG Global-Resource Bundle Foundation — Global Resource Grants.
--
-- Depends on 0001_iam_schema.sql (iam.users) having already been applied.
-- Does NOT alter, drop, or touch iam.security_events or any table defined by
-- 0001/0002/0003/0004 in any way — grant/revoke provenance for the global
-- 'rag_index' resource lives in its own, separate iam.global_resource_grant_
-- events table (explicit user decision: iam.security_events' event_type is a
-- closed enum reserved for the existing case/session/auth event set and must
-- not be extended to carry an unrelated resource-grant vocabulary).
--
-- No new row is inserted into mutation.mutation_resources here — the
-- 'global:rag_index' advisory-lock resource key this grants table's subject
-- (rag_index) corresponds to was already seeded by 0003_mutation_journal.sql;
-- this migration only adds the IAM-side grant/authorization bookkeeping for
-- who may inspect/build/activate that resource, never a second lock registry.
--
-- CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS throughout —
-- additive, idempotent, safely re-runnable, matching 0001-0004's own
-- convention. No ALTER of any pre-existing table appears in this file.

BEGIN;

-- ---------------------------------------------------------------
-- iam.global_resource_grants — one row per grant *attempt* (surrogate
-- BIGSERIAL identity PK, never a natural-key PK) so that revoke-then-
-- re-grant opens a brand-new history row instead of colliding with, or
-- silently reviving, the old one. `resource` is closed to the single
-- literal 'rag_index' for now (a real, enforced constraint — not a
-- comment-only convention) — a future global resource would need its
-- own migration to widen this set, never a silent widening here.
-- `capability` is closed to the three roles this Foundation defines:
-- inspect (read bundle/grant state), build (produce a new immutable
-- bundle), activate (flip the live pointer). Whether one operator holds
-- all three, or they are split across people, is entirely an
-- operational/grant-issuing decision outside this schema's concern —
-- this table places no structural limit on how many capabilities one
-- user may hold simultaneously.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS iam.global_resource_grants (
    id                   BIGSERIAL PRIMARY KEY,
    user_id              BIGINT NOT NULL REFERENCES iam.users(id),
    resource             TEXT NOT NULL CHECK (resource = 'rag_index'),
    capability           TEXT NOT NULL CHECK (capability IN ('inspect', 'build', 'activate')),
    granted_by_user_id   BIGINT NOT NULL REFERENCES iam.users(id),
    granted_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at           TIMESTAMPTZ NULL,
    revoked_by_user_id   BIGINT NULL REFERENCES iam.users(id),
    CHECK ((revoked_at IS NULL) = (revoked_by_user_id IS NULL))
);

-- At most one ACTIVE (not-yet-revoked) grant per (user, resource,
-- capability) — mirrors iam.case_assignments' own active-uniqueness
-- partial index (0001) exactly. A revoked row never blocks a fresh
-- grant of the same shape: it simply is not covered by this WHERE
-- clause, so re-granting after a revoke inserts a new row with its own
-- id rather than erroring or resurrecting the old one.
CREATE UNIQUE INDEX IF NOT EXISTS global_resource_grants_active_uniq
    ON iam.global_resource_grants (user_id, resource, capability)
    WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS global_resource_grants_user_id_idx
    ON iam.global_resource_grants (user_id);

CREATE INDEX IF NOT EXISTS global_resource_grants_active_capability_idx
    ON iam.global_resource_grants (resource, capability) WHERE revoked_at IS NULL;

-- ---------------------------------------------------------------
-- iam.global_resource_grant_events — independent, append-only audit
-- trail of every grant/revoke decision, keyed by its own PK (never
-- reusing global_resource_grants.id) so a grant row's full lifecycle
-- (creation, and later revocation) is visible as two distinct, ordered
-- event rows rather than being inferred from column mutation. Every
-- write here is additive-only; no UPDATE/DELETE against this table is
-- ever issued by this project's own code.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS iam.global_resource_grant_events (
    id               BIGSERIAL PRIMARY KEY,
    grant_id         BIGINT NOT NULL REFERENCES iam.global_resource_grants(id),
    event_type       TEXT NOT NULL CHECK (event_type IN ('grant_created', 'grant_revoked')),
    actor_user_id    BIGINT NOT NULL REFERENCES iam.users(id),
    subject_user_id  BIGINT NOT NULL REFERENCES iam.users(id),
    resource         TEXT NOT NULL CHECK (resource = 'rag_index'),
    capability       TEXT NOT NULL CHECK (capability IN ('inspect', 'build', 'activate')),
    occurred_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS global_resource_grant_events_grant_id_idx
    ON iam.global_resource_grant_events (grant_id);

CREATE INDEX IF NOT EXISTS global_resource_grant_events_occurred_at_idx
    ON iam.global_resource_grant_events (occurred_at);

COMMIT;
