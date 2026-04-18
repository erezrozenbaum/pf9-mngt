-- =====================================================================
-- MIGRATION: Per-tenant branding override support
-- Target version: v1.85.6
--
-- Adds a project_id column to tenant_portal_branding so that each
-- tenant organisation (Keystone project) can have its own branding
-- that overrides the control-plane-level defaults.
--
-- The empty string '' in project_id means "global / CP-level default".
-- Per-project rows use the Keystone project UUID as project_id.
--
-- Local dev:
--   docker cp db/migrate_per_tenant_branding.sql pf9_db:/tmp/migrate_per_tenant_branding.sql
--   docker exec pf9_db psql -U pf9 -d pf9_mgmt -f /tmp/migrate_per_tenant_branding.sql
--
-- Kubernetes production:
--   kubectl cp db/migrate_per_tenant_branding.sql \
--     pf9-mngt/pf9-db-0:/tmp/migrate_per_tenant_branding.sql
--   kubectl exec -n pf9-mngt pf9-db-0 -- \
--     psql -U postgres -d pf9_mgmt -f /tmp/migrate_per_tenant_branding.sql
-- =====================================================================

BEGIN;

-- Step 1: Add project_id column (empty string = global/CP-level default)
ALTER TABLE tenant_portal_branding
    ADD COLUMN IF NOT EXISTS project_id TEXT NOT NULL DEFAULT '';

-- Step 2: Drop the old single-column primary key
ALTER TABLE tenant_portal_branding
    DROP CONSTRAINT IF EXISTS tenant_portal_branding_pkey;

-- Step 3: Add composite primary key (control_plane_id, project_id)
ALTER TABLE tenant_portal_branding
    ADD CONSTRAINT tenant_portal_branding_pkey
    PRIMARY KEY (control_plane_id, project_id);

COMMIT;
