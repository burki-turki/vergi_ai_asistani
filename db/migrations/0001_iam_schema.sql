-- Row 19B — Identity / Session / Authorization schema.
-- Applies cleanly to an empty database. No Row 1-18 tables are touched.
-- Idempotent guards use IF NOT EXISTS so a re-run (e.g. in a test harness)
-- does not fail; this is a convenience for local/test runs, not a
-- statement about production migration tooling (Row 19D's concern).

BEGIN;

CREATE SCHEMA IF NOT EXISTS iam;

-- ---------------------------------------------------------------
-- iam.users — one row per human identity known to the application.
-- authz_version is the single authoritative revocation counter:
-- bumped on every role/assignment/disable change, compared against
-- each session's role_version_at_issue on every request.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS iam.users (
    id             BIGSERIAL PRIMARY KEY,
    display_name   TEXT NOT NULL,
    disabled       BOOLEAN NOT NULL DEFAULT FALSE,
    authz_version  BIGINT NOT NULL DEFAULT 1,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------
-- iam.external_identities — the (issuer, subject) pairing that
-- /auth/callback looks up. No JIT creation ever inserts here except
-- through provision-user or bootstrap-first-admin (both CLI-only).
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS iam.external_identities (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES iam.users(id),
    issuer      TEXT NOT NULL,
    subject     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (issuer, subject)
);

CREATE INDEX IF NOT EXISTS external_identities_user_id_idx
    ON iam.external_identities (user_id);

-- ---------------------------------------------------------------
-- iam.user_roles — global admin grant ONLY. lawyer/analyst live
-- exclusively in case_assignments below; this table cannot express
-- them (CHECK enforces it), eliminating dual-authority ambiguity.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS iam.user_roles (
    user_id     BIGINT NOT NULL REFERENCES iam.users(id),
    role        TEXT NOT NULL CHECK (role = 'admin'),
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, role)
);

-- ---------------------------------------------------------------
-- iam.case_assignments — the ONLY source of lawyer/analyst
-- authority, scoped per case. One active role per (user_id, case_id):
-- enforced by a partial unique index, not an inline UNIQUE(...)
-- WHERE clause (invalid PostgreSQL constraint syntax).
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS iam.case_assignments (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES iam.users(id),
    case_id     TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('lawyer', 'analyst')),
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at  TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS case_assignments_active_uniq
    ON iam.case_assignments (user_id, case_id)
    WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS case_assignments_case_id_idx
    ON iam.case_assignments (case_id) WHERE revoked_at IS NULL;

-- ---------------------------------------------------------------
-- iam.sessions — opaque server-side session. Only the SHA-256 hash
-- of the token is stored, never the token itself. role_version_at_
-- issue is a snapshot compared against iam.users.authz_version on
-- every request; a mismatch forces live re-derivation.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS iam.sessions (
    id                     BIGSERIAL PRIMARY KEY,
    user_id                BIGINT NOT NULL REFERENCES iam.users(id),
    token_hash             TEXT NOT NULL UNIQUE,
    role_version_at_issue  BIGINT NOT NULL,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    idle_expires_at        TIMESTAMPTZ NOT NULL,
    absolute_expires_at    TIMESTAMPTZ NOT NULL,
    revoked_at             TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON iam.sessions (user_id);

-- ---------------------------------------------------------------
-- iam.oidc_login_transactions — server-side OIDC transaction state.
-- state/nonce are stored as hashes (never plaintext); the PKCE
-- verifier is AEAD-encrypted (recoverable, needed for token
-- exchange) with explicit key_id/alg metadata for fail-closed
-- decryption. One-time consumption is enforced by consumed_at.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS iam.oidc_login_transactions (
    id                          BIGSERIAL PRIMARY KEY,
    state_hash                  TEXT NOT NULL UNIQUE,
    nonce_hash                  TEXT NOT NULL,
    pkce_verifier_ciphertext    BYTEA NOT NULL,
    pkce_verifier_nonce         BYTEA NOT NULL,
    pkce_key_id                 TEXT NOT NULL,
    pkce_enc_alg                TEXT NOT NULL,
    required_authentication_context_id TEXT NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at                  TIMESTAMPTZ NOT NULL,
    consumed_at                 TIMESTAMPTZ NULL
);

-- ---------------------------------------------------------------
-- iam.bootstrap_state — DB-enforced singleton guaranteeing only one
-- concurrent `bootstrap-first-admin` invocation can ever succeed.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS iam.bootstrap_state (
    id               BOOLEAN PRIMARY KEY,
    bootstrapped_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (id)
);

-- ---------------------------------------------------------------
-- iam.security_events — closed, typed schema. No JSONB. One CHECK-
-- constrained event_type enum; every write goes through a single
-- typed writer function in ui/services/security_events.py.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS iam.security_events (
    id                              BIGSERIAL PRIMARY KEY,
    event_type                      TEXT NOT NULL CHECK (event_type IN (
        'login_success',
        'login_denied_unknown_identity',
        'login_denied_disabled_user',
        'login_denied_mfa_absent',
        'logout',
        'session_revoked',
        'session_expired_idle',
        'session_expired_absolute',
        'authz_denied',
        'csrf_rejected',
        'admin_role_granted',
        'admin_role_revoked',
        'case_assignment_granted',
        'case_assignment_revoked',
        'user_provisioned',
        'user_disabled',
        'user_enabled',
        'bootstrap_first_admin'
    )),
    occurred_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id                         BIGINT NULL REFERENCES iam.users(id),
    actor_user_id                   BIGINT NULL REFERENCES iam.users(id),
    session_id                      BIGINT NULL REFERENCES iam.sessions(id),
    case_id                         TEXT NULL,
    role                            TEXT NULL CHECK (role IN ('admin', 'lawyer', 'analyst')),
    granted                         BOOLEAN NULL,
    reason_code                     TEXT NULL CHECK (reason_code IN (
        'unknown_identity', 'disabled_user', 'mfa_claim_absent',
        'mfa_claim_malformed', 'mfa_claim_mismatch', 'capability_denied',
        'assignment_revoked', 'csrf_mismatch', 'origin_mismatch',
        'idle_timeout', 'absolute_timeout', 'admin_action', 'user_action'
    )),
    requested_capability            TEXT NULL CHECK (requested_capability IN (
        'read', 'mutate'
    )),
    mfa_satisfied                   BOOLEAN NULL,
    mfa_assurance_level             TEXT NULL CHECK (mfa_assurance_level IN (
        'none', 'entra_free_unavailable', 'entra_p1_context_satisfied'
    )),
    mfa_assurance_policy_version    TEXT NULL,
    authenticated_at                TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS security_events_occurred_at_idx
    ON iam.security_events (occurred_at);
CREATE INDEX IF NOT EXISTS security_events_user_id_idx
    ON iam.security_events (user_id);

COMMIT;
