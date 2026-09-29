-- Pilot Readiness Step 8 / Slice 8A — least-privilege runtime role contract.
--
-- Depends on 0001-0005 having already been applied. Does NOT create, alter or
-- drop a single table, column, index, sequence or schema: this migration only
-- REVOKEs from PUBLIC and GRANTs the exact, source-derived minimum privilege
-- set to two pre-existing LOGIN roles. 0001-0005 remain byte-immutable.
--
-- ROLES ARE NOT CREATED HERE. CREATE ROLE is cluster-wide, not database-scoped;
-- creating login roles from a per-database migration would leak them into every
-- other database on the cluster (including a disposable test cluster). The three
-- roles are created once by operational bootstrap; if any of them is absent, or
-- carries an attribute more powerful than the contract allows, this migration
-- stops fail-closed and grants nothing.
--
-- ROLE NAMES ARE PARAMETRIC, DEFAULTS ARE CANONICAL. psql variables
-- owner_role / app_role / admin_role default to the canonical local-pilot names
-- vergi_owner / vergi_app / vergi_iam_admin. The pilot and the official gate
-- always use the defaults; only the privilege test overrides them, with
-- tokenized throwaway roles in its own throwaway database, so that the
-- "role missing" and "role over-privileged" branches can be exercised without
-- ever creating or dropping a canonical cluster-wide role.
--
-- Values reach PL/pgSQL through session-scoped custom GUCs written OUTSIDE any
-- dollar-quoted body (`SELECT set_config(...)` with :'var' in an ordinary SQL
-- literal position) and are read back with current_setting(). psql does not
-- interpolate variables inside dollar-quoted strings, so :'var' is never
-- written into a DO body. Every dynamic identifier goes through format('%I');
-- there is no raw string interpolation anywhere in this file.
--
-- ATOMICITY. One transaction: preconditions -> REVOKE/GRANT -> postconditions.
-- Any failure at any stage rolls the whole thing back; GRANT and REVOKE are
-- transactional in PostgreSQL, so a partial privilege state cannot survive.
--
-- IDEMPOTENCY. GRANT and REVOKE are naturally idempotent and the postcondition
-- is an exact-set match, so re-applying this file is safe and is a no-op.
--
-- ROLLBACK. If this migration has not been applied, rollback is "do not apply
-- it". Once applied, the privilege state is NEVER corrected with ad-hoc
-- GRANT/REVOKE/ALTER: any change or reversal must go into a new, separately
-- numbered and separately approved migration. A runbook or an operator SQL
-- session is not a substitute for migration history.
--
-- DELIBERATELY UNAUTHORIZED PATHS (fail-closed by construction, not oversight):
--   * ui/auth_routes.py, ui/services/session_store.py and the web-login branch
--     of ui/services/security_events.py INSERT into iam.oidc_login_transactions,
--     iam.sessions and iam.security_events. Neither app_role nor admin_role is
--     granted those writes. Browser login therefore cannot reach the database
--     until Pilot Readiness Step 11 opens it under its own, separately approved
--     role/migration contract. This is NOT a login bypass: it is the database
--     layer agreeing with the application layer that this path is closed.
--   * app_role is granted nothing at all on iam.security_events,
--     iam.oidc_login_transactions, iam.external_identities, iam.bootstrap_state
--     or iam.global_resource_grant_events.
--   * admin_role is granted nothing at all on mutation.mutation_journal or
--     iam.oidc_login_transactions.

\set ON_ERROR_STOP on

\if :{?owner_role}
\else
\set owner_role 'vergi_owner'
\endif

\if :{?app_role}
\else
\set app_role 'vergi_app'
\endif

\if :{?admin_role}
\else
\set admin_role 'vergi_iam_admin'
\endif

BEGIN;

SELECT set_config('vergi.owner_role', :'owner_role', false) AS vergi_set_owner \gset
SELECT set_config('vergi.app_role', :'app_role', false) AS vergi_set_app \gset
SELECT set_config('vergi.admin_role', :'admin_role', false) AS vergi_set_admin \gset

-- ---------------------------------------------------------------
-- PRECONDITIONS. Nothing below this block runs unless every one of
-- them holds.
-- ---------------------------------------------------------------
DO $pre$
DECLARE
    v_owner  text := btrim(coalesce(current_setting('vergi.owner_role', true), ''));
    v_app    text := btrim(coalesce(current_setting('vergi.app_role', true), ''));
    v_admin  text := btrim(coalesce(current_setting('vergi.admin_role', true), ''));
    v_role   text;
    v_rec    record;
    v_missing text;
BEGIN
    -- 1. role parameters are present and non-empty. An unset GUC or an
    --    explicitly empty -v value must NOT silently fall back to a canonical
    --    name: that would apply production grants under a test invocation.
    IF v_owner = '' OR v_app = '' OR v_admin = '' THEN
        RAISE EXCEPTION
            'VERGI 0006: role parameters must be non-empty (owner/app/admin resolved to %/%/%)',
            quote_literal(v_owner), quote_literal(v_app), quote_literal(v_admin);
    END IF;

    IF v_owner = v_app OR v_owner = v_admin OR v_app = v_admin THEN
        RAISE EXCEPTION 'VERGI 0006: owner, app and admin roles must be three distinct roles';
    END IF;

    -- 2. all three roles exist.
    FOREACH v_role IN ARRAY ARRAY[v_owner, v_app, v_admin] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            RAISE EXCEPTION
                'VERGI 0006: role % does not exist; operational bootstrap must create it before this migration',
                quote_literal(v_role);
        END IF;
    END LOOP;

    -- 3. none of them carries a dangerous attribute.
    FOR v_rec IN
        SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls
        FROM pg_roles
        WHERE rolname IN (v_owner, v_app, v_admin)
    LOOP
        IF v_rec.rolsuper OR v_rec.rolcreatedb OR v_rec.rolcreaterole
           OR v_rec.rolreplication OR v_rec.rolbypassrls THEN
            RAISE EXCEPTION
                'VERGI 0006: role % is more privileged than the contract allows (super=%, createdb=%, createrole=%, replication=%, bypassrls=%)',
                quote_literal(v_rec.rolname), v_rec.rolsuper, v_rec.rolcreatedb,
                v_rec.rolcreaterole, v_rec.rolreplication, v_rec.rolbypassrls;
        END IF;
    END LOOP;

    -- 4. the current database is owned by the owner role.
    IF NOT EXISTS (
        SELECT 1
        FROM pg_database d
        JOIN pg_roles r ON r.oid = d.datdba
        WHERE d.datname = current_database() AND r.rolname = v_owner
    ) THEN
        RAISE EXCEPTION
            'VERGI 0006: database % is not owned by %',
            quote_literal(current_database()), quote_literal(v_owner);
    END IF;

    -- 5. both schemas exist and are owned by the owner role.
    IF (SELECT count(*) FROM pg_namespace WHERE nspname IN ('iam', 'mutation')) <> 2 THEN
        RAISE EXCEPTION 'VERGI 0006: both the iam and mutation schemas must exist (0001-0005 applied)';
    END IF;

    SELECT string_agg(n.nspname, ', ' ORDER BY n.nspname) INTO v_missing
    FROM pg_namespace n
    JOIN pg_roles r ON r.oid = n.nspowner
    WHERE n.nspname IN ('iam', 'mutation') AND r.rolname <> v_owner;

    IF v_missing IS NOT NULL THEN
        RAISE EXCEPTION
            'VERGI 0006: schema(s) % are not owned by %', v_missing, quote_literal(v_owner);
    END IF;

    -- 6. this migration is being applied by the owner role itself.
    IF current_user <> v_owner THEN
        RAISE EXCEPTION
            'VERGI 0006: must be applied as % (current_user is %)',
            quote_literal(v_owner), quote_literal(current_user);
    END IF;

    -- 7. every grant target exists.
    SELECT string_agg(t, ', ' ORDER BY t) INTO v_missing
    FROM unnest(ARRAY[
        'iam.users', 'iam.external_identities', 'iam.user_roles',
        'iam.case_assignments', 'iam.sessions', 'iam.oidc_login_transactions',
        'iam.bootstrap_state', 'iam.security_events',
        'iam.global_resource_grants', 'iam.global_resource_grant_events',
        'mutation.mutation_resources', 'mutation.mutation_journal',
        'iam.users_id_seq', 'iam.external_identities_id_seq',
        'iam.case_assignments_id_seq', 'iam.security_events_id_seq',
        'iam.global_resource_grants_id_seq', 'iam.global_resource_grant_events_id_seq',
        'mutation.mutation_journal_id_seq'
    ]) AS t
    WHERE to_regclass(t) IS NULL;

    IF v_missing IS NOT NULL THEN
        RAISE EXCEPTION 'VERGI 0006: missing grant target(s): %', v_missing;
    END IF;
END
$pre$;

-- ---------------------------------------------------------------
-- REVOKE from PUBLIC, then GRANT the exact minimum matrix.
-- ---------------------------------------------------------------
DO $grants$
DECLARE
    v_owner text := btrim(current_setting('vergi.owner_role'));
    v_app   text := btrim(current_setting('vergi.app_role'));
    v_admin text := btrim(current_setting('vergi.admin_role'));
BEGIN
    EXECUTE 'REVOKE ALL ON SCHEMA iam FROM PUBLIC';
    EXECUTE 'REVOKE ALL ON SCHEMA mutation FROM PUBLIC';
    EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database());

    EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I, %I, %I',
                   current_database(), v_owner, v_app, v_admin);
    EXECUTE format('GRANT USAGE ON SCHEMA iam, mutation TO %I, %I', v_app, v_admin);

    -- app_role: ui/cli_mutate.py runtime. No DELETE anywhere, no DDL, no IAM
    -- management write, no access to security_events or oidc_login_transactions.
    EXECUTE format(
        'GRANT SELECT ON iam.users, iam.case_assignments, iam.sessions, '
        'iam.user_roles, iam.global_resource_grants TO %I', v_app);
    EXECUTE format('GRANT SELECT, INSERT ON mutation.mutation_resources TO %I', v_app);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE ON mutation.mutation_journal TO %I', v_app);
    EXECUTE format('GRANT USAGE ON SEQUENCE mutation.mutation_journal_id_seq TO %I', v_app);

    -- admin_role: scripts/iam_admin.py and scripts/global_resource_grants.py.
    -- No mutation.mutation_journal write of any kind, no DDL.
    EXECUTE format(
        'GRANT SELECT, INSERT, UPDATE ON iam.users, iam.external_identities, '
        'iam.case_assignments, iam.security_events, iam.bootstrap_state, '
        'iam.user_roles, iam.global_resource_grants TO %I', v_admin);
    EXECUTE format('GRANT DELETE ON iam.user_roles TO %I', v_admin);
    EXECUTE format('GRANT SELECT, UPDATE ON iam.sessions TO %I', v_admin);
    EXECUTE format('GRANT INSERT ON iam.global_resource_grant_events TO %I', v_admin);
    EXECUTE format('GRANT SELECT ON mutation.mutation_resources TO %I', v_admin);
    EXECUTE format(
        'GRANT USAGE ON SEQUENCE iam.users_id_seq, iam.external_identities_id_seq, '
        'iam.case_assignments_id_seq, iam.security_events_id_seq, '
        'iam.global_resource_grants_id_seq, iam.global_resource_grant_events_id_seq '
        'TO %I', v_admin);
END
$grants$;

-- ---------------------------------------------------------------
-- POSTCONDITIONS. Exact-set match: a MISSING privilege and an EXTRA
-- privilege both fail, and both roll the whole transaction back.
-- ---------------------------------------------------------------
DO $post$
DECLARE
    v_app      text := btrim(current_setting('vergi.app_role'));
    v_admin    text := btrim(current_setting('vergi.admin_role'));
    v_actual   text[];
    v_expected text[];
BEGIN
    -- app_role: exact directly-granted privilege set over iam.* + mutation.*
    SELECT coalesce(array_agg(x ORDER BY x COLLATE "C"), ARRAY[]::text[]) INTO v_actual
    FROM (
        SELECT n.nspname || '.' || c.relname || ':' || a.privilege_type AS x
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN LATERAL aclexplode(
            coalesce(c.relacl,
                     acldefault((CASE c.relkind WHEN 'S' THEN 's' ELSE 'r' END)::"char",
                                c.relowner))) AS a
        WHERE n.nspname IN ('iam', 'mutation')
          AND c.relkind IN ('r', 'S')
          AND a.grantee = (SELECT oid FROM pg_roles WHERE rolname = v_app)
    ) s;

    v_expected := ARRAY[
        'iam.case_assignments:SELECT',
        'iam.global_resource_grants:SELECT',
        'iam.sessions:SELECT',
        'iam.user_roles:SELECT',
        'iam.users:SELECT',
        'mutation.mutation_journal:INSERT',
        'mutation.mutation_journal:SELECT',
        'mutation.mutation_journal:UPDATE',
        'mutation.mutation_journal_id_seq:USAGE',
        'mutation.mutation_resources:INSERT',
        'mutation.mutation_resources:SELECT'
    ];

    IF v_actual IS DISTINCT FROM v_expected THEN
        RAISE EXCEPTION
            'VERGI 0006: app role privilege set mismatch; missing=% extra=%',
            (SELECT coalesce(string_agg(e, ', ' ORDER BY e COLLATE "C"), '(none)')
             FROM unnest(v_expected) e WHERE e <> ALL (v_actual)),
            (SELECT coalesce(string_agg(g, ', ' ORDER BY g COLLATE "C"), '(none)')
             FROM unnest(v_actual) g WHERE g <> ALL (v_expected));
    END IF;

    -- admin_role: exact directly-granted privilege set over iam.* + mutation.*
    SELECT coalesce(array_agg(x ORDER BY x COLLATE "C"), ARRAY[]::text[]) INTO v_actual
    FROM (
        SELECT n.nspname || '.' || c.relname || ':' || a.privilege_type AS x
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN LATERAL aclexplode(
            coalesce(c.relacl,
                     acldefault((CASE c.relkind WHEN 'S' THEN 's' ELSE 'r' END)::"char",
                                c.relowner))) AS a
        WHERE n.nspname IN ('iam', 'mutation')
          AND c.relkind IN ('r', 'S')
          AND a.grantee = (SELECT oid FROM pg_roles WHERE rolname = v_admin)
    ) s;

    v_expected := ARRAY[
        'iam.bootstrap_state:INSERT',
        'iam.bootstrap_state:SELECT',
        'iam.bootstrap_state:UPDATE',
        'iam.case_assignments:INSERT',
        'iam.case_assignments:SELECT',
        'iam.case_assignments:UPDATE',
        'iam.case_assignments_id_seq:USAGE',
        'iam.external_identities:INSERT',
        'iam.external_identities:SELECT',
        'iam.external_identities:UPDATE',
        'iam.external_identities_id_seq:USAGE',
        'iam.global_resource_grant_events:INSERT',
        'iam.global_resource_grant_events_id_seq:USAGE',
        'iam.global_resource_grants:INSERT',
        'iam.global_resource_grants:SELECT',
        'iam.global_resource_grants:UPDATE',
        'iam.global_resource_grants_id_seq:USAGE',
        'iam.security_events:INSERT',
        'iam.security_events:SELECT',
        'iam.security_events:UPDATE',
        'iam.security_events_id_seq:USAGE',
        'iam.sessions:SELECT',
        'iam.sessions:UPDATE',
        'iam.user_roles:DELETE',
        'iam.user_roles:INSERT',
        'iam.user_roles:SELECT',
        'iam.user_roles:UPDATE',
        'iam.users:INSERT',
        'iam.users:SELECT',
        'iam.users:UPDATE',
        'iam.users_id_seq:USAGE',
        'mutation.mutation_resources:SELECT'
    ];

    IF v_actual IS DISTINCT FROM v_expected THEN
        RAISE EXCEPTION
            'VERGI 0006: admin role privilege set mismatch; missing=% extra=%',
            (SELECT coalesce(string_agg(e, ', ' ORDER BY e COLLATE "C"), '(none)')
             FROM unnest(v_expected) e WHERE e <> ALL (v_actual)),
            (SELECT coalesce(string_agg(g, ', ' ORDER BY g COLLATE "C"), '(none)')
             FROM unnest(v_actual) g WHERE g <> ALL (v_expected));
    END IF;

    -- PUBLIC must hold no USAGE and no CREATE on either schema. PUBLIC is a
    -- pseudo-role and is NOT accepted as the user argument of
    -- has_schema_privilege(); it is grantee OID 0 inside the ACL, so the check
    -- goes through pg_namespace.nspacl + aclexplode(). A NULL nspacl means the
    -- built-in default, which is acldefault('n', nspowner) - owner only, no
    -- PUBLIC entry. Both schemas must exist, otherwise this fails closed
    -- instead of silently reporting "no PUBLIC privileges found".
    IF NOT (
        (SELECT count(*) = 2 FROM pg_namespace WHERE nspname IN ('iam', 'mutation'))
        AND NOT EXISTS (
            SELECT 1
            FROM pg_namespace AS n
            CROSS JOIN LATERAL aclexplode(
                coalesce(n.nspacl, acldefault('n'::"char", n.nspowner))) AS a
            WHERE n.nspname IN ('iam', 'mutation')
              AND a.grantee = 0
              AND a.privilege_type IN ('USAGE', 'CREATE')
        )
    ) THEN
        RAISE EXCEPTION
            'VERGI 0006: PUBLIC still holds USAGE or CREATE on iam/mutation, or a schema is missing';
    END IF;
END
$post$;

COMMIT;
