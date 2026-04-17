-- =====================================================================
-- MIGRATION: Tenant Portal — Phase P0 (Security) + Phase P1 (Schema)
-- Target version: v1.84.0
-- Run against both environments — see Rule 1 in tenant_portal_plan.md
--
-- Local dev:
--   docker cp db/migrate_tenant_portal.sql pf9_db:/tmp/migrate_tenant_portal.sql
--   docker exec pf9_db psql -U pf9 -d pf9_mgmt -f /tmp/migrate_tenant_portal.sql
--
-- Kubernetes production:
--   kubectl cp db/migrate_tenant_portal.sql \
--     pf9-mngt/pf9-db-0:/tmp/migrate_tenant_portal.sql
--   kubectl exec -n pf9-mngt pf9-db-0 -- \
--     psql -U postgres -d pf9_mgmt -f /tmp/migrate_tenant_portal.sql
--
-- AFTER running this migration, set the DB role password:
--   Local dev:
--     docker exec pf9_db psql -U pf9 -d pf9_mgmt \
--       -c "ALTER ROLE tenant_portal_role WITH PASSWORD '<dev-password>'"
--   Kubernetes (password comes from sealed secret):
--     kubectl exec -n pf9-mngt pf9-db-0 -- psql -U postgres -d pf9_mgmt \
--       -c "ALTER ROLE tenant_portal_role WITH PASSWORD '<from-k8s-secret>'"
--
-- Design notes:
--   - PART 1 creates all NEW objects. No locks on existing live tables.
--   - PARTS 2-7 each enable RLS on one existing table in its own short
--     transaction. Separate transactions ensure the pf9_api shared lock
--     on each table has time to clear between attempts, preventing the
--     deadlock that occurs when multiple ALTER TABLEs compete inside one
--     long transaction.
--   - lock_timeout = 30s: if pf9_api is busy, the statement waits up to
--     30 s and fails cleanly rather than deadlocking.
--   - The admin app (pf9_api) connects as POSTGRES_USER (PostgreSQL
--     superuser). Superusers bypass RLS automatically. No existing
--     query behaviour changes.
--   - Safe to re-run: guards on IF NOT EXISTS, DROP … IF EXISTS,
--     ON CONFLICT DO NOTHING.
-- =====================================================================

SET lock_timeout = '30s';

-- =====================================================================
-- PART 1 — New objects only (no locks on existing tables)
-- =====================================================================
BEGIN;

-- Role ------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'tenant_portal_role') THEN
        CREATE ROLE tenant_portal_role LOGIN;
        RAISE NOTICE 'Created role tenant_portal_role. Set password from secret before deploying.';
    ELSE
        RAISE NOTICE 'Role tenant_portal_role already exists, skipping.';
    END IF;
END $$;

DO $$
DECLARE v_dbname TEXT := current_database();
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO tenant_portal_role', v_dbname);
END $$;

GRANT USAGE ON SCHEMA public TO tenant_portal_role;

-- Safe view over pf9_control_planes (hides username + password_enc) -----
CREATE OR REPLACE VIEW tenant_cp_view AS
    SELECT id, name, auth_url, is_enabled, display_color, tags
    FROM   pf9_control_planes
    WHERE  is_enabled = TRUE;

GRANT SELECT ON tenant_cp_view TO tenant_portal_role;

-- Grants on pre-existing tables -----------------------------------------
GRANT SELECT                  ON servers, volumes, snapshots, snapshot_records TO tenant_portal_role;
GRANT SELECT                  ON flavors, inventory_runs TO tenant_portal_role;
GRANT SELECT, INSERT, UPDATE  ON restore_jobs    TO tenant_portal_role;
GRANT SELECT                  ON pf9_regions        TO tenant_portal_role;
GRANT SELECT                  ON role_assignments   TO tenant_portal_role;
GRANT SELECT                  ON projects           TO tenant_portal_role;

-- Make all enabled runbooks visible to tenant portal (idempotent data fix)
UPDATE runbooks SET is_tenant_visible = true WHERE enabled = true AND is_tenant_visible = false;
-- Admin-only runbooks that tenants should NOT see (idempotent)
UPDATE runbooks SET is_tenant_visible = false WHERE name IN (
    -- Infrastructure / platform-admin operations
    'hypervisor_maintenance_evacuate',
    'cluster_capacity_planner',
    'capacity_forecast',
    'diagnostics_bundle',
    -- Tenant account management (admin perspective)
    'tenant_offboarding',
    'quota_adjustment',
    -- Admin-scoped reporting / intelligence tools
    'upgrade_opportunity_detector',
    'monthly_executive_snapshot',
    'cost_leakage_report',
    'org_usage_report',
    -- Forecasting tools that scan across all tenants
    'snapshot_quota_forecast',
    -- Security / compliance tools that scan ALL tenants/users (not scoped to one project)
    'image_lifecycle_audit',
    'network_isolation_audit',
    'security_compliance_audit',
    'user_last_login',
    -- Operational runbooks scoped to admin-level infrastructure actions
    'disaster_recovery_drill',
    'orphan_resource_cleanup',
    'stuck_vm_remediation'
);
GRANT SELECT                  ON users              TO tenant_portal_role;
GRANT SELECT                  ON runbooks        TO tenant_portal_role;
GRANT SELECT, INSERT          ON tenant_action_log TO tenant_portal_role;
GRANT INSERT                  ON auth_audit_log  TO tenant_portal_role;
GRANT INSERT                  ON notification_log TO tenant_portal_role;

-- New table: permanent tenant audit log ---------------------------------
CREATE TABLE IF NOT EXISTS tenant_action_log (
    id               BIGSERIAL    PRIMARY KEY,
    keystone_user_id TEXT         NOT NULL,
    username         VARCHAR(255) NOT NULL,
    control_plane_id TEXT         NOT NULL,
    action           VARCHAR(100) NOT NULL,
    resource_type    VARCHAR(50),
    resource_id      TEXT,
    project_id       TEXT,
    region_id        TEXT,
    ip_address       INET,
    user_agent       TEXT,
    timestamp        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    success          BOOLEAN      NOT NULL DEFAULT true,
    details          JSONB
);
CREATE INDEX IF NOT EXISTS idx_tenant_action_log_user_ts ON tenant_action_log (keystone_user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_tenant_action_log_cp_ts   ON tenant_action_log (control_plane_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_tenant_action_log_action  ON tenant_action_log (action, timestamp DESC);
GRANT INSERT        ON tenant_action_log            TO tenant_portal_role;
GRANT USAGE, SELECT ON SEQUENCE tenant_action_log_id_seq TO tenant_portal_role;

-- New table: per-user access allowlist (default-deny) -------------------
CREATE TABLE IF NOT EXISTS tenant_portal_access (
    id               BIGSERIAL    PRIMARY KEY,
    keystone_user_id TEXT         NOT NULL,
    control_plane_id TEXT         NOT NULL REFERENCES pf9_control_planes(id),
    enabled          BOOLEAN      NOT NULL DEFAULT false,
    mfa_required     BOOLEAN      NOT NULL DEFAULT false,
    notes            TEXT,
    granted_by       TEXT,
    granted_at       TIMESTAMPTZ,
    revoked_by       TEXT,
    revoked_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (keystone_user_id, control_plane_id)
);
CREATE INDEX IF NOT EXISTS idx_tenant_portal_access_cp_enabled
    ON tenant_portal_access (control_plane_id, enabled);
GRANT SELECT ON tenant_portal_access TO tenant_portal_role;

-- New table: per-CP branding --------------------------------------------
CREATE TABLE IF NOT EXISTS tenant_portal_branding (
    control_plane_id TEXT         PRIMARY KEY REFERENCES pf9_control_planes(id),
    company_name     VARCHAR(255) NOT NULL DEFAULT 'Cloud Portal',
    logo_url         TEXT,
    favicon_url      TEXT,
    primary_color    CHAR(7)      NOT NULL DEFAULT '#1A73E8',
    accent_color     CHAR(7)      NOT NULL DEFAULT '#F29900',
    support_email    TEXT,
    support_url      TEXT,
    welcome_message  TEXT,
    footer_text      TEXT,
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);
GRANT SELECT ON tenant_portal_branding TO tenant_portal_role;

-- New table: tenant TOTP MFA secrets (RLS applied in PART 7) -----------
CREATE TABLE IF NOT EXISTS tenant_portal_mfa (
    id                BIGSERIAL    PRIMARY KEY,
    keystone_user_id  TEXT         NOT NULL,
    control_plane_id  TEXT         NOT NULL REFERENCES pf9_control_planes(id),
    totp_secret       TEXT         NOT NULL,
    backup_codes      TEXT[]       NOT NULL,
    enrolled_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_used_at      TIMESTAMPTZ,
    used_backup_codes INT[]        NOT NULL DEFAULT '{}',
    UNIQUE (keystone_user_id, control_plane_id)
);
GRANT SELECT, INSERT, UPDATE ON tenant_portal_mfa     TO tenant_portal_role;
GRANT USAGE, SELECT ON SEQUENCE tenant_portal_mfa_id_seq TO tenant_portal_role;

-- Opt-in column on runbooks (default false — existing rows unaffected) --
ALTER TABLE runbooks
    ADD COLUMN IF NOT EXISTS is_tenant_visible BOOLEAN NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS idx_runbooks_tenant_visible
    ON runbooks (is_tenant_visible) WHERE is_tenant_visible = true;

-- New table: project-scoped runbook tags --------------------------------
CREATE TABLE IF NOT EXISTS runbook_project_tags (
    runbook_name TEXT NOT NULL REFERENCES runbooks(name) ON DELETE CASCADE,
    project_id   TEXT NOT NULL,
    PRIMARY KEY (runbook_name, project_id)
);
CREATE INDEX IF NOT EXISTS idx_runbook_project_tags_project
    ON runbook_project_tags (project_id);
GRANT SELECT ON runbook_project_tags TO tenant_portal_role;

-- Tenant role permissions seed ------------------------------------------
INSERT INTO role_permissions (role, resource, action) VALUES
    ('tenant', 'snapshots', 'read'),
    ('tenant', 'restore',   'write'),
    ('tenant', 'servers',   'read'),
    ('tenant', 'volumes',   'read')
ON CONFLICT DO NOTHING;

COMMIT;

-- =====================================================================
-- PART 2 — RLS on servers (own short transaction)
-- =====================================================================
BEGIN;
ALTER TABLE servers ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_portal_isolation ON servers;
CREATE POLICY tenant_portal_isolation ON servers
    AS PERMISSIVE FOR SELECT TO tenant_portal_role
    USING (
        project_id = ANY(string_to_array(current_setting('app.tenant_project_ids', true), ','))
        AND region_id = ANY(string_to_array(current_setting('app.tenant_region_ids', true), ','))
    );
COMMIT;

-- =====================================================================
-- PART 3 — RLS on volumes
-- =====================================================================
BEGIN;
ALTER TABLE volumes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_portal_isolation ON volumes;
CREATE POLICY tenant_portal_isolation ON volumes
    AS PERMISSIVE FOR SELECT TO tenant_portal_role
    USING (
        project_id = ANY(string_to_array(current_setting('app.tenant_project_ids', true), ','))
        AND region_id = ANY(string_to_array(current_setting('app.tenant_region_ids', true), ','))
    );
COMMIT;

-- =====================================================================
-- PART 4 — RLS on snapshots
-- =====================================================================
BEGIN;
ALTER TABLE snapshots ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_portal_isolation ON snapshots;
CREATE POLICY tenant_portal_isolation ON snapshots
    AS PERMISSIVE FOR SELECT TO tenant_portal_role
    USING (
        project_id = ANY(string_to_array(current_setting('app.tenant_project_ids', true), ','))
        AND region_id = ANY(string_to_array(current_setting('app.tenant_region_ids', true), ','))
    );
COMMIT;

-- =====================================================================
-- PART 5 — RLS on snapshot_records
-- =====================================================================
BEGIN;
ALTER TABLE snapshot_records ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_portal_isolation ON snapshot_records;
CREATE POLICY tenant_portal_isolation ON snapshot_records
    AS PERMISSIVE FOR SELECT TO tenant_portal_role
    USING (
        project_id = ANY(string_to_array(current_setting('app.tenant_project_ids', true), ','))
        AND region_id = ANY(string_to_array(current_setting('app.tenant_region_ids', true), ','))
    );
COMMIT;

-- =====================================================================
-- PART 6 — RLS on restore_jobs (project-scoped only; no region_id column)
-- =====================================================================
BEGIN;
ALTER TABLE restore_jobs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_portal_isolation_select ON restore_jobs;
CREATE POLICY tenant_portal_isolation_select ON restore_jobs
    AS PERMISSIVE FOR SELECT TO tenant_portal_role
    USING (project_id = ANY(string_to_array(current_setting('app.tenant_project_ids', true), ',')));
DROP POLICY IF EXISTS tenant_portal_isolation_insert ON restore_jobs;
CREATE POLICY tenant_portal_isolation_insert ON restore_jobs
    AS PERMISSIVE FOR INSERT TO tenant_portal_role
    WITH CHECK (project_id = ANY(string_to_array(current_setting('app.tenant_project_ids', true), ',')));
DROP POLICY IF EXISTS tenant_portal_isolation_update ON restore_jobs;
CREATE POLICY tenant_portal_isolation_update ON restore_jobs
    AS PERMISSIVE FOR UPDATE TO tenant_portal_role
    USING (project_id = ANY(string_to_array(current_setting('app.tenant_project_ids', true), ',')));
COMMIT;

-- =====================================================================
-- PART 7 — RLS on tenant_portal_mfa (per-user row isolation)
-- The tenant portal sets app.tenant_keystone_user_id + app.tenant_cp_id
-- at the start of every authenticated request. Without these being set,
-- all rows are filtered (default-deny). Each user sees only their row.
-- =====================================================================
BEGIN;
ALTER TABLE tenant_portal_mfa ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_mfa_isolation ON tenant_portal_mfa;
CREATE POLICY tenant_mfa_isolation ON tenant_portal_mfa
    AS PERMISSIVE FOR ALL TO tenant_portal_role
    USING (
        keystone_user_id = current_setting('app.tenant_keystone_user_id', true)
        AND control_plane_id = current_setting('app.tenant_cp_id', true)
    )
    WITH CHECK (
        keystone_user_id = current_setting('app.tenant_keystone_user_id', true)
        AND control_plane_id = current_setting('app.tenant_cp_id', true)
    );
COMMIT;

-- =====================================================================
-- PART 8 — v1.85.0: grants for new networking / provisioning endpoints
-- networks, subnets, ports, security_groups, security_group_rules, images
-- =====================================================================
BEGIN;
GRANT SELECT ON networks, subnets, ports TO tenant_portal_role;
GRANT SELECT ON security_groups, security_group_rules TO tenant_portal_role;
GRANT SELECT ON images TO tenant_portal_role;
COMMIT;
