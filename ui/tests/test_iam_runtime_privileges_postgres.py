# ============================================================
# Pilot Readiness Step 8 / Slice 8A - REAL PostgreSQL proof for
# db/migrations/0006_iam_runtime_privileges.sql.
#
# WHAT THIS FILE OWNS (decision III-a): the WHOLE of 0006's behaviour -
# positive apply under the right owner, every fail-closed precondition
# branch, mid-stream/postcondition atomicity, idempotent re-apply, and the
# real app/admin privilege matrix exercised over genuine connections as the
# genuine least-privileged roles. test_iam_migrations_isolated.py deliberately
# does NOT test 0006 even partially; it only closes its own 0004/0005 gap.
#
# ISOLATION - WHY THIS NEVER POLLUTES THE GATE CLUSTER OR THE GATE DATABASE
# ------------------------------------------------------------------------
# PostgreSQL roles are CLUSTER-wide, not database-scoped. The canonical
# local-pilot names (vergi_owner / vergi_app / vergi_iam_admin) are created
# once by operational bootstrap and are shared by every database on the
# cluster, so a test may not create or drop them - and could not exercise the
# "role missing" branch if it had to use them. This file therefore:
#
#   * NEVER creates, alters or drops a canonical role;
#   * generates a per-run token (pid + random hex) and creates its OWN three
#     tokenized LOGIN roles, refusing to start if any of those names already
#     exists (so teardown can only ever drop what this run created);
#   * creates its OWN throwaway databases and applies 0001-0006 inside them,
#     passing the tokenized role names through 0006's psql variables;
#   * touches the main gate database NOT AT ALL - no read, no write, no
#     migration, no sentinel change, and nothing under data/cases/;
#   * drops every database and every tokenized role it created, then proves
#     in-process that no tokenized residue is left behind.
#
# CREDENTIALS (G2/G3 contract) - passwords are generated with `secrets`, live
# only in memory and in a per-run temporary passfile whose ACL is verified
# before it is used. They are NEVER printed, never written to a report, never
# placed on a command line, and never exported as PGPASSWORD or PGPASSFILE:
# the passfile path travels as libpq's `passfile` CONNECTION parameter, both
# for psycopg and for psql's connection URI.
#
# WHY THE NEGATIVE PASSFILE CONTROL IS NOT VACUOUS: a wrong/empty passfile
# only proves anything if the server actually demands a password. On a cluster
# whose pg_hba.conf trusts everyone on loopback the assertion would pass while
# proving nothing. This file therefore reads pg_hba_file_rules first and FAILS
# (never skips) if a blanket `trust` rule would apply to its tokenized roles.
#
# SKIPPED with an explicit message if no reachable PostgreSQL is configured via
# VERGI_TEST_PG_DSN, matching this project's other real-DB files - never
# silently treated as a pass.
#
# Run: python -m ui.tests.test_iam_runtime_privileges_postgres
# (requires: VERGI_TEST_PG_DSN=<any reachable disposable database>,
#  VERGI_TEST_PG_SUPERUSER_AVAILABLE=1, VERGI_TEST_PSQL_BIN=<psql.exe>,
#  VERGI_TEST_PG_MAINTENANCE_DB=postgres, PGHOST/PGPORT/PGUSER)
# ============================================================

import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import uuid
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"
for p in (REPO_ROOT,):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

passed = 0
failed = 0
MODULE = "test_iam_runtime_privileges_postgres"


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label} {detail}")


def summarize_and_exit(code=None):
    print(f"--- {MODULE}: {passed} passed, {failed} failed ---")
    sys.exit((1 if failed else 0) if code is None else code)


PG_DB = os.environ.get("VERGI_TEST_PG_DSN")
if not PG_DB:
    print(
        "SKIPPED real PostgreSQL least-privilege checks - VERGI_TEST_PG_DSN not set to a "
        "reachable disposable database in this run. NOT EXECUTED, not a pass."
    )
    summarize_and_exit(0)

try:
    import psycopg
except Exception as exc:  # pragma: no cover - environment-dependent
    print(
        "SKIPPED real PostgreSQL least-privilege checks - psycopg is not importable in this "
        f"run ({type(exc).__name__}). NOT EXECUTED, not a pass."
    )
    summarize_and_exit(0)

# A superuser is not optional for this file: it must create and drop its own
# roles and databases. This is a FAILURE, not a skip - the module cannot do its
# job and must not pretend it did.
if os.environ.get("VERGI_TEST_PG_SUPERUSER_AVAILABLE") != "1":
    check("preflight: VERGI_TEST_PG_SUPERUSER_AVAILABLE=1 (needed to create throwaway roles/databases)",
          False, "not set; this module cannot create its own tokenized roles")
    summarize_and_exit()

PSQL_BIN = os.environ.get("VERGI_TEST_PSQL_BIN") or shutil.which("psql")
if not PSQL_BIN or not Path(PSQL_BIN).is_file():
    check("preflight: VERGI_TEST_PSQL_BIN names an existing psql executable", False,
          "0006 uses psql meta-commands (\\set/\\if/:'var') and cannot be applied through psycopg")
    summarize_and_exit()

MAINT_DB = os.environ.get("VERGI_TEST_PG_MAINTENANCE_DB", "postgres")
PGHOST = os.environ.get("PGHOST", "127.0.0.1")
PGPORT = os.environ.get("PGPORT", "5432")

TOKEN = "t8a_%d_%s" % (os.getpid(), uuid.uuid4().hex[:8])
R_OWNER = TOKEN + "_owner"
R_APP = TOKEN + "_app"
R_ADMIN = TOKEN + "_admin"
DB_MAIN = TOKEN + "_main"      # full 0001-0005, then a successful 0006
DB_NEG = TOKEN + "_neg"        # full 0001-0005, only ever sees FAILING 0006 runs
DB_PARTIAL = TOKEN + "_part"   # 0001+0002 only: missing grant targets
ALL_DBS = (DB_MAIN, DB_NEG, DB_PARTIAL)
ALL_ROLES = (R_OWNER, R_APP, R_ADMIN)

MIGRATIONS_FULL = ("0001_iam_schema", "0002_mutation_resources", "0003_mutation_journal",
                   "0004_mutation_reconciliation_provenance", "0005_global_resource_grants")
MIGRATION_0006 = "0006_iam_runtime_privileges"

_passwords = {}
_tmp_dir = None
_passfile = None
_wrong_passfile = None


def super_conn(dbname):
    return psycopg.connect(dbname=dbname, host=PGHOST, port=PGPORT, connect_timeout=10, autocommit=True)


def super_exec(dbname, sql, params=None):
    with super_conn(dbname) as c, c.cursor() as cur:
        cur.execute(sql, params)


def super_one(dbname, sql, params=None):
    with super_conn(dbname) as c, c.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return row[0] if row else None


def role_uri(role, dbname, passfile):
    return "postgresql://%s@%s:%s/%s?passfile=%s" % (
        urllib.parse.quote(role), PGHOST, PGPORT, urllib.parse.quote(dbname),
        urllib.parse.quote(str(passfile).replace("\\", "/"), safe="/:"))


def apply_migration(name, dbname, role=R_OWNER, passfile=None, variables=None):
    """Applies one migration file through psql. Returns (returncode, tail-of-output).
    No password and no passfile ever reaches the environment: credentials travel
    only inside the connection URI's `passfile` parameter."""
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in ("PGPASSWORD", "PGPASSFILE", "PGSERVICE", "PGSERVICEFILE",
                                "PGDATABASE", "PGUSER", "PGHOST", "PGPORT")}
    env["PGCONNECT_TIMEOUT"] = "10"
    cmd = [PSQL_BIN, "-v", "ON_ERROR_STOP=1", "-q",
           "-d", role_uri(role, dbname, passfile or _passfile)]
    for key, value in (variables or {}).items():
        cmd += ["-v", "%s=%s" % (key, value)]
    cmd += ["-f", str(MIGRATIONS_DIR / (name + ".sql"))]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, timeout=180)
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or ""))[-1200:]


def direct_privileges(dbname, role):
    sql = """
        SELECT n.nspname || '.' || c.relname || ':' || a.privilege_type
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN LATERAL aclexplode(coalesce(c.relacl,
            acldefault((CASE c.relkind WHEN 'S' THEN 's' ELSE 'r' END)::"char", c.relowner))) AS a
        WHERE n.nspname IN ('iam', 'mutation') AND c.relkind IN ('r', 'S')
          AND a.grantee = (SELECT oid FROM pg_roles WHERE rolname = %s)
    """
    with super_conn(dbname) as c, c.cursor() as cur:
        cur.execute(sql, (role,))
        return sorted(row[0] for row in cur.fetchall())


def denied(conn, sql, params=None):
    """Runs one statement expecting an InsufficientPrivilege. Returns True when
    permission was refused, False when it SUCCEEDED (which is a real finding)."""
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
    except psycopg.errors.InsufficientPrivilege:
        conn.rollback()
        return True
    except Exception:
        conn.rollback()
        return False
    conn.rollback()
    return False


def acl_is_current_user_only(path):
    """Windows: the passfile and its directory must not be readable by anyone
    but the current user. libpq does NOT check this on Windows, so the test
    checks it instead of assuming."""
    if os.name != "nt":
        mode = Path(path).stat().st_mode & 0o077
        return mode == 0, "posix mode bits %o" % (Path(path).stat().st_mode & 0o777)
    proc = subprocess.run(["icacls", str(path)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60)
    text = proc.stdout or ""
    bad = [tok for tok in ("Everyone", "BUILTIN\\Users", "Authenticated Users", "BUILTIN\\Kullan")
           if tok in text]
    return (proc.returncode == 0 and not bad), ("broad trustees: %s" % ", ".join(bad) if bad else "")


EXPECTED_APP = [
    "iam.case_assignments:SELECT",
    "iam.global_resource_grants:SELECT",
    "iam.sessions:SELECT",
    "iam.user_roles:SELECT",
    "iam.users:SELECT",
    "mutation.mutation_journal:INSERT",
    "mutation.mutation_journal:SELECT",
    "mutation.mutation_journal:UPDATE",
    "mutation.mutation_journal_id_seq:USAGE",
    "mutation.mutation_resources:INSERT",
    "mutation.mutation_resources:SELECT",
]

EXPECTED_ADMIN = [
    "iam.bootstrap_state:INSERT", "iam.bootstrap_state:SELECT", "iam.bootstrap_state:UPDATE",
    "iam.case_assignments:INSERT", "iam.case_assignments:SELECT", "iam.case_assignments:UPDATE",
    "iam.case_assignments_id_seq:USAGE",
    "iam.external_identities:INSERT", "iam.external_identities:SELECT",
    "iam.external_identities:UPDATE", "iam.external_identities_id_seq:USAGE",
    "iam.global_resource_grant_events:INSERT",
    "iam.global_resource_grant_events_id_seq:USAGE",
    "iam.global_resource_grants:INSERT", "iam.global_resource_grants:SELECT",
    "iam.global_resource_grants:UPDATE", "iam.global_resource_grants_id_seq:USAGE",
    "iam.security_events:INSERT", "iam.security_events:SELECT", "iam.security_events:UPDATE",
    "iam.security_events_id_seq:USAGE",
    "iam.sessions:SELECT", "iam.sessions:UPDATE",
    "iam.user_roles:DELETE", "iam.user_roles:INSERT", "iam.user_roles:SELECT",
    "iam.user_roles:UPDATE",
    "iam.users:INSERT", "iam.users:SELECT", "iam.users:UPDATE", "iam.users_id_seq:USAGE",
    "mutation.mutation_resources:SELECT",
]


def teardown():
    for db in ALL_DBS:
        try:
            super_exec(MAINT_DB, 'DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % db)
        except Exception:
            pass
    for role in ALL_ROLES:
        try:
            super_exec(MAINT_DB, 'DROP ROLE IF EXISTS "%s"' % role)
        except Exception:
            pass
    if _tmp_dir and Path(_tmp_dir).exists():
        shutil.rmtree(_tmp_dir, ignore_errors=True)


try:
    # -----------------------------------------------------------------
    # P. Preflight: the cluster must really demand a password from these
    #    roles, and none of this run's names may already exist.
    # -----------------------------------------------------------------
    with super_conn(MAINT_DB) as c, c.cursor() as cur:
        cur.execute("SELECT count(*) FROM pg_hba_file_rules "
                    "WHERE auth_method = 'trust' AND 'all' = ANY(user_name)")
        blanket_trust = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM pg_roles WHERE rolname = ANY(%s)", (list(ALL_ROLES),))
        pre_roles = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM pg_database WHERE datname = ANY(%s)", (list(ALL_DBS),))
        pre_dbs = cur.fetchone()[0]

    check("P1: cluster does NOT blanket-trust every role on this connection type "
          "(otherwise the passfile negative control would be vacuous)",
          blanket_trust == 0,
          f"{blanket_trust} pg_hba rule(s) grant trust to 'all' users; give the superuser trust "
          f"but require scram-sha-256 for every other role")
    check("P2: none of this run's tokenized role names already exists (teardown may only drop what it created)",
          pre_roles == 0, f"{pre_roles} pre-existing")
    check("P3: none of this run's tokenized database names already exists",
          pre_dbs == 0, f"{pre_dbs} pre-existing")
    if failed:
        summarize_and_exit()

    # -----------------------------------------------------------------
    # S. Setup: tokenized roles, throwaway databases, ACL-verified passfile.
    # -----------------------------------------------------------------
    # CREATE ROLE is a utility statement: PostgreSQL does not accept bind
    # parameters in it, so the password is composed into the statement with
    # psycopg's own literal quoting (injection-safe). It still never reaches a
    # command line, an environment variable, a log or this module's output.
    from psycopg import sql as _sql

    for role in ALL_ROLES:
        _passwords[role] = secrets.token_urlsafe(24)
        with super_conn(MAINT_DB) as c, c.cursor() as cur:
            cur.execute(_sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(_sql.Identifier(role), _sql.Literal(_passwords[role])))
    for db in ALL_DBS:
        super_exec(MAINT_DB, 'CREATE DATABASE "%s" OWNER "%s"' % (db, R_OWNER))

    _tmp_dir = tempfile.mkdtemp(prefix="vergi_slice8a_")
    if os.name == "nt":
        subprocess.run(["icacls", _tmp_dir, "/inheritance:r", "/grant:r",
                        "%s:(OI)(CI)F" % os.environ.get("USERNAME", "")],
                       capture_output=True, text=True, timeout=60)
    else:
        os.chmod(_tmp_dir, 0o700)

    _passfile = Path(_tmp_dir) / "pgpass.conf"
    lines = ["%s:%s:%s:%s:%s" % (PGHOST, PGPORT, db, role, _passwords[role])
             for db in ALL_DBS for role in ALL_ROLES]
    _passfile.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")
    if os.name != "nt":
        os.chmod(_passfile, 0o600)

    _wrong_passfile = Path(_tmp_dir) / "pgpass_wrong.conf"
    _wrong_passfile.write_text(
        "\n".join("%s:%s:%s:%s:%s" % (PGHOST, PGPORT, db, role, "not-the-password")
                  for db in ALL_DBS for role in ALL_ROLES) + "\n",
        encoding="ascii", newline="\n")
    if os.name != "nt":
        os.chmod(_wrong_passfile, 0o600)

    ok, detail = acl_is_current_user_only(_passfile)
    check("S1: passfile ACL is restricted to the current user before any password is used", ok, detail)
    if not ok:
        summarize_and_exit()

    check("S2: no password or passfile value is exported to the environment",
          "PGPASSWORD" not in os.environ and "PGPASSFILE" not in os.environ,
          "this module must authenticate through the connection parameter only")

    for db in (DB_MAIN, DB_NEG):
        for name in MIGRATIONS_FULL:
            rc, tail = apply_migration(name, db)
            if rc != 0:
                check(f"S3: {name} applies cleanly to {db}", False, tail)
                summarize_and_exit()
    for name in ("0001_iam_schema", "0002_mutation_resources"):
        rc, tail = apply_migration(name, DB_PARTIAL)
        if rc != 0:
            check(f"S3: {name} applies cleanly to the partial database", False, tail)
            summarize_and_exit()
    check("S3: migrations 0001-0005 applied as the tokenized owner over a passfile URI "
          "(no PGPASSWORD, no PGPASSFILE)", True)

    TOKEN_VARS = {"owner_role": R_OWNER, "app_role": R_APP, "admin_role": R_ADMIN}

    # -----------------------------------------------------------------
    # C. Credential contract (G2/G3).
    # -----------------------------------------------------------------
    good_uri = role_uri(R_APP, DB_MAIN, _passfile)
    try:
        conn = psycopg.connect(good_uri, connect_timeout=10)
        conn.close()
        connected = True
        cdetail = ""
    except Exception as exc:
        connected = False
        cdetail = type(exc).__name__
    check("C1: correct passfile passed as a CONNECTION parameter authenticates successfully",
          connected, cdetail)

    for label, uri in (("wrong", role_uri(R_APP, DB_MAIN, _wrong_passfile)),
                       ("absent", role_uri(R_APP, DB_MAIN, Path(_tmp_dir) / "does_not_exist.conf"))):
        try:
            conn = psycopg.connect(uri, connect_timeout=10)
            conn.close()
            refused = False
        except psycopg.OperationalError:
            refused = True
        except Exception:
            refused = False
        check(f"C2: {label} passfile -> connection REFUSED (negative control, cluster really demands a password)",
              refused)

    # -----------------------------------------------------------------
    # F. 0006 fail-closed branches, all against DB_NEG / DB_PARTIAL, which
    #    never receive a successful 0006.
    # -----------------------------------------------------------------
    rc, tail = apply_migration(MIGRATION_0006, DB_NEG,
                               variables=dict(TOKEN_VARS, app_role=""))
    check("F1: empty role parameter -> fail-closed (never silently falls back to a canonical name)",
          rc != 0 and "must be non-empty" in tail, f"rc={rc} {tail[-200:]}")

    rc, tail = apply_migration(MIGRATION_0006, DB_NEG,
                               variables=dict(TOKEN_VARS, app_role=TOKEN + "_absent"))
    check("F2: missing role -> fail-closed with the role named",
          rc != 0 and "does not exist" in tail, f"rc={rc} {tail[-200:]}")

    rc, tail = apply_migration(MIGRATION_0006, DB_NEG,
                               variables=dict(TOKEN_VARS, admin_role=R_APP))
    check("F3: the same role given twice -> fail-closed (three distinct roles required)",
          rc != 0 and "distinct" in tail, f"rc={rc} {tail[-200:]}")

    super_exec(MAINT_DB, 'ALTER ROLE "%s" CREATEDB' % R_APP)
    rc, tail = apply_migration(MIGRATION_0006, DB_NEG, variables=TOKEN_VARS)
    super_exec(MAINT_DB, 'ALTER ROLE "%s" NOCREATEDB' % R_APP)
    check("F4: over-privileged role (CREATEDB) -> fail-closed",
          rc != 0 and "more privileged than the contract allows" in tail, f"rc={rc} {tail[-200:]}")

    super_exec(MAINT_DB, 'ALTER DATABASE "%s" OWNER TO "%s"' % (DB_NEG, R_ADMIN))
    rc, tail = apply_migration(MIGRATION_0006, DB_NEG, variables=TOKEN_VARS)
    super_exec(MAINT_DB, 'ALTER DATABASE "%s" OWNER TO "%s"' % (DB_NEG, R_OWNER))
    check("F5: wrong database owner -> fail-closed",
          rc != 0 and "is not owned by" in tail, f"rc={rc} {tail[-200:]}")

    super_exec(DB_NEG, 'ALTER SCHEMA iam OWNER TO "%s"' % R_ADMIN)
    rc, tail = apply_migration(MIGRATION_0006, DB_NEG, variables=TOKEN_VARS)
    super_exec(DB_NEG, 'ALTER SCHEMA iam OWNER TO "%s"' % R_OWNER)
    check("F6: wrong schema owner -> fail-closed",
          rc != 0 and "not owned by" in tail, f"rc={rc} {tail[-200:]}")

    rc, tail = apply_migration(MIGRATION_0006, DB_NEG, role=R_ADMIN, variables=TOKEN_VARS)
    check("F7: applied by a role other than the owner -> fail-closed",
          rc != 0 and "must be applied as" in tail, f"rc={rc} {tail[-200:]}")

    rc, tail = apply_migration(MIGRATION_0006, DB_PARTIAL, variables=TOKEN_VARS)
    check("F8: missing grant targets (only 0001+0002 applied) -> fail-closed",
          rc != 0 and ("missing grant target" in tail or "must exist" in tail),
          f"rc={rc} {tail[-200:]}")

    # -----------------------------------------------------------------
    # A. Atomicity: a POSTCONDITION failure must roll back 0006's OWN
    #    grants while leaving a pre-existing, separately committed grant
    #    untouched. 0006 revokes only from PUBLIC, never from the roles,
    #    so the extra grant is what makes the postcondition fail.
    # -----------------------------------------------------------------
    super_exec(DB_NEG, 'GRANT DELETE ON mutation.mutation_journal TO "%s"' % R_APP)
    before = direct_privileges(DB_NEG, R_APP)
    rc, tail = apply_migration(MIGRATION_0006, DB_NEG, variables=TOKEN_VARS)
    after = direct_privileges(DB_NEG, R_APP)
    check("A1: an EXTRA pre-existing grant makes the exact-set postcondition fail",
          rc != 0 and "privilege set mismatch" in tail, f"rc={rc} {tail[-200:]}")
    check("A2: the failing run granted NOTHING - 0006's own grants were rolled back mid-stream",
          after == before and "mutation.mutation_journal:INSERT" not in after,
          f"before={before} after={after}")
    check("A3: the separately committed pre-existing grant survived (it was outside 0006's transaction)",
          "mutation.mutation_journal:DELETE" in after, after)
    super_exec(DB_NEG, 'REVOKE DELETE ON mutation.mutation_journal FROM "%s"' % R_APP)

    # -----------------------------------------------------------------
    # G. Positive apply + idempotency on DB_MAIN.
    # -----------------------------------------------------------------
    rc, tail = apply_migration(MIGRATION_0006, DB_MAIN, variables=TOKEN_VARS)
    check("G1: 0006 applies cleanly as the owner with tokenized role parameters", rc == 0, tail)
    check("G2: app role holds EXACTLY the expected privilege set",
          direct_privileges(DB_MAIN, R_APP) == sorted(EXPECTED_APP),
          direct_privileges(DB_MAIN, R_APP))
    check("G3: admin role holds EXACTLY the expected privilege set",
          direct_privileges(DB_MAIN, R_ADMIN) == sorted(EXPECTED_ADMIN),
          direct_privileges(DB_MAIN, R_ADMIN))

    rc2, tail2 = apply_migration(MIGRATION_0006, DB_MAIN, variables=TOKEN_VARS)
    check("G4: re-applying 0006 is safe and idempotent (exit 0, identical privilege set)",
          rc2 == 0 and direct_privileges(DB_MAIN, R_APP) == sorted(EXPECTED_APP)
          and direct_privileges(DB_MAIN, R_ADMIN) == sorted(EXPECTED_ADMIN), tail2)

    pub = super_one(DB_MAIN, """
        SELECT (SELECT count(*) = 2 FROM pg_namespace WHERE nspname IN ('iam','mutation'))
           AND NOT EXISTS (SELECT 1 FROM pg_namespace n
                CROSS JOIN LATERAL aclexplode(coalesce(n.nspacl,
                    acldefault('n'::"char", n.nspowner))) a
                WHERE n.nspname IN ('iam','mutation') AND a.grantee = 0
                  AND a.privilege_type IN ('USAGE','CREATE'))
    """)
    check("G5: PUBLIC holds no USAGE and no CREATE on iam/mutation "
          "(checked via nspacl+aclexplode, grantee 0 - has_schema_privilege does not accept PUBLIC)",
          pub is True, pub)

    # -----------------------------------------------------------------
    # M. The real privilege matrix, over genuine connections as the
    #    genuine least-privileged roles.
    # -----------------------------------------------------------------
    app = psycopg.connect(role_uri(R_APP, DB_MAIN, _passfile), connect_timeout=10)
    adm = psycopg.connect(role_uri(R_ADMIN, DB_MAIN, _passfile), connect_timeout=10)
    try:
        with app.cursor() as cur:
            cur.execute("SELECT count(*) FROM iam.users")
            cur.execute("SELECT count(*) FROM iam.case_assignments")
            cur.execute("SELECT count(*) FROM iam.sessions")
            cur.execute("SELECT count(*) FROM iam.user_roles")
            cur.execute("SELECT count(*) FROM iam.global_resource_grants")
        app.rollback()
        check("M1: app role can run every read its production call sites need", True)

        with app.cursor() as cur:
            cur.execute("INSERT INTO mutation.mutation_resources (resource_key) VALUES (%s) "
                        "ON CONFLICT (resource_key) DO NOTHING", ("case:" + TOKEN,))
            cur.execute("SELECT advisory_lock_id FROM mutation.mutation_resources "
                        "WHERE resource_key = %s", ("case:" + TOKEN,))
            lock_id = cur.fetchone()[0]
            cur.execute("SELECT pg_advisory_lock(%s)", (lock_id,))
            cur.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
        app.commit()
        check("M2: app role can get-or-create a case resource key and take/release its advisory lock "
              "(mutation_lock.py's real path, no superuser)", True)

        with app.cursor() as cur:
            cur.execute(
                "INSERT INTO mutation.mutation_journal "
                "(idempotency_key, resource_key, action_family, actor_label, target_ref, "
                "request_fingerprint, state) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'prepared') RETURNING id",
                (TOKEN + "-idem", "case:" + TOKEN, "approval.fact", "cli:" + TOKEN,
                 "case_" + TOKEN + "/facts.json", TOKEN + "-fp"))
            jid = cur.fetchone()[0]
            # A plain column UPDATE: this file proves PRIVILEGES, not the
            # journal's own state machine, so it deliberately does not try to
            # drive a state transition that carries its own CHECK constraints.
            cur.execute("UPDATE mutation.mutation_journal SET pre_hash=%s WHERE id=%s",
                        (TOKEN + "-pre", jid))
        app.commit()
        check("M3: app role can INSERT and UPDATE the mutation journal (sequence USAGE reached)", True)

        check("M4: app role CANNOT insert a web-login session (Step 11 path stays closed)",
              denied(app, "INSERT INTO iam.sessions (user_id, token_hash, role_version_at_issue, "
                          "idle_expires_at, absolute_expires_at) VALUES (1,'x',1,now(),now())"))
        check("M5: app role CANNOT insert an OIDC login transaction (Step 11 path stays closed)",
              denied(app, "INSERT INTO iam.oidc_login_transactions (state_hash, nonce_hash, "
                          "pkce_verifier_ciphertext, pkce_verifier_nonce, pkce_key_id, pkce_enc_alg, "
                          "required_authentication_context_id, expires_at) "
                          "VALUES ('a','b','\\x00','\\x00','k','alg','ctx', now())"))
        check("M6: app role CANNOT write a security event",
              denied(app, "INSERT INTO iam.security_events (event_type) VALUES ('login_success')"))
        check("M7: app role CANNOT perform IAM administration (INSERT into iam.users)",
              denied(app, "INSERT INTO iam.users (display_name) VALUES ('x')"))
        check("M8: app role CANNOT delete an admin role grant",
              denied(app, "DELETE FROM iam.user_roles WHERE role = 'admin'"))
        check("M9: app role CANNOT run DDL in the iam schema",
              denied(app, "CREATE TABLE iam.slice8a_should_not_exist (id int)"))
        check("M10: app role CANNOT run DDL in the mutation schema",
              denied(app, "CREATE TABLE mutation.slice8a_should_not_exist (id int)"))

        with adm.cursor() as cur:
            cur.execute("INSERT INTO iam.users (display_name) VALUES (%s) RETURNING id",
                        ("slice8a-" + TOKEN,))
            uid = cur.fetchone()[0]
            cur.execute("INSERT INTO iam.external_identities (user_id, issuer, subject) "
                        "VALUES (%s, %s, %s)", (uid, "urn:vergi:local-cli", TOKEN))
            cur.execute("INSERT INTO iam.user_roles (user_id, role) VALUES (%s, 'admin')", (uid,))
            cur.execute("INSERT INTO iam.case_assignments (user_id, case_id, role) "
                        "VALUES (%s, %s, 'lawyer')", (uid, "case_" + TOKEN))
            cur.execute("INSERT INTO iam.security_events (event_type, user_id) "
                        "VALUES ('user_provisioned', %s)", (uid,))
            cur.execute("UPDATE iam.users SET authz_version = authz_version + 1 WHERE id=%s", (uid,))
            cur.execute("SELECT advisory_lock_id FROM mutation.mutation_resources "
                        "WHERE resource_key = 'global:iam'")
            iam_lock = cur.fetchone()[0]
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (iam_lock,))
            cur.execute("DELETE FROM iam.user_roles WHERE user_id = %s", (uid,))
        adm.commit()
        check("M11: admin role can run the whole iam_admin.py chain (provision, grant, assign, "
              "security event, global:iam lock, revoke-role DELETE)", True)

        with adm.cursor() as cur:
            cur.execute("INSERT INTO iam.global_resource_grants "
                        "(user_id, resource, capability, granted_by_user_id) "
                        "VALUES (%s,'rag_index','build',%s) RETURNING id", (uid, uid))
            gid = cur.fetchone()[0]
            cur.execute("INSERT INTO iam.global_resource_grant_events "
                        "(grant_id, event_type, actor_user_id, subject_user_id, resource, capability) "
                        "VALUES (%s,'grant_created',%s,%s,'rag_index','build')", (gid, uid, uid))
            cur.execute("UPDATE iam.global_resource_grants SET revoked_at = now(), "
                        "revoked_by_user_id = %s WHERE id = %s", (uid, gid))
            cur.execute("SELECT count(*) FROM iam.global_resource_grants WHERE id = %s", (gid,))
        adm.commit()
        check("M12: admin role can run global_resource_grants.py's real DB sequence "
              "(grants INSERT/UPDATE/SELECT + grant_events INSERT)", True)

        check("M13: admin role CANNOT read grant_events (INSERT-only, exactly as the source uses it)",
              denied(adm, "SELECT count(*) FROM iam.global_resource_grant_events"))
        check("M14: admin role CANNOT update grant_events",
              denied(adm, "UPDATE iam.global_resource_grant_events SET event_type='grant_revoked'"))
        check("M15: admin role CANNOT write the mutation journal",
              denied(adm, "INSERT INTO mutation.mutation_journal (idempotency_key, resource_key, "
                          "action_family, actor_label, target_ref, request_fingerprint, state) "
                          "VALUES ('x','y','z','a','t','f','prepared')"))
        check("M16: admin role CANNOT create a case resource key (no INSERT on mutation_resources)",
              denied(adm, "INSERT INTO mutation.mutation_resources (resource_key) VALUES ('case:x8a')"))
        check("M17: admin role CANNOT insert a web-login session (Step 11 path stays closed)",
              denied(adm, "INSERT INTO iam.sessions (user_id, token_hash, role_version_at_issue, "
                          "idle_expires_at, absolute_expires_at) VALUES (1,'y',1,now(),now())"))
        check("M18: admin role CANNOT touch iam.oidc_login_transactions at all",
              denied(adm, "SELECT count(*) FROM iam.oidc_login_transactions"))
        check("M19: admin role CANNOT run DDL",
              denied(adm, "CREATE TABLE iam.slice8a_admin_should_not_exist (id int)"))
    finally:
        app.close()
        adm.close()

    owner_attrs = super_one(MAINT_DB,
                            "SELECT NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication "
                            "OR rolbypassrls) FROM pg_roles WHERE rolname = %s", (R_OWNER,))
    check("M20: the owner role that applied every migration is NOT a superuser and holds no "
          "CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS", owner_attrs is True, owner_attrs)

except Exception as error:  # noqa: BLE001 - one honest failure line, never a traceback
    check("unhandled exception during the Slice 8A privilege run", False,
          f"{type(error).__name__}: {str(error)[:300]}")
finally:
    teardown()

try:
    with super_conn(MAINT_DB) as c, c.cursor() as cur:
        cur.execute("SELECT count(*) FROM pg_roles WHERE rolname LIKE %s", (TOKEN + "%",))
        role_residue = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM pg_database WHERE datname LIKE %s", (TOKEN + "%",))
        db_residue = cur.fetchone()[0]
    check("Z1: teardown left no tokenized role and no tokenized database on the cluster",
          role_residue == 0 and db_residue == 0, f"roles={role_residue} databases={db_residue}")
except Exception as error:  # pragma: no cover
    check("Z1: residue check could run", False, type(error).__name__)

check("Z2: teardown removed this run's temporary passfile directory",
      _tmp_dir is None or not Path(_tmp_dir).exists(), str(_tmp_dir))

summarize_and_exit()
