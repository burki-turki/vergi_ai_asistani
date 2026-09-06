-- Row 19B — single, shared, authoritative mutation-resource registry.
-- This is the ONLY resource-key -> advisory-lock-id registry in the
-- system. Row 19C must reuse this exact table for its own resource
-- keys rather than create a second registry. This migration does not
-- create any file-write journal / reconciliation table (mutation_
-- journal) — that remains exclusively Row 19C's scope.

BEGIN;

CREATE SCHEMA IF NOT EXISTS mutation;

CREATE TABLE IF NOT EXISTS mutation.mutation_resources (
    resource_key      TEXT PRIMARY KEY,
    advisory_lock_id  BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE NOT NULL
);

-- advisory_lock_id is database-assigned via GENERATED ALWAYS AS IDENTITY
-- (backed by Postgres's own sequence) — never derived with hashtext()
-- or any other non-authoritative hash. Uniqueness is guaranteed by the
-- UNIQUE constraint + identity sequence, not by hash collision-freedom.

INSERT INTO mutation.mutation_resources (resource_key)
VALUES ('global:iam')
ON CONFLICT (resource_key) DO NOTHING;

COMMIT;
