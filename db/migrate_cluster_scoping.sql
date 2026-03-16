-- ============================================================
-- Migration Planner: Cluster-level scoping / exclusion
-- v1.66.2
-- Idempotent — safe to re-run (ADD COLUMN IF NOT EXISTS)
-- ============================================================

-- Add include_in_plan + exclude_reason to migration_clusters,
-- mirroring the same columns on migration_tenants.
-- Default true so existing clusters are unaffected after migration.

ALTER TABLE migration_clusters
    ADD COLUMN IF NOT EXISTS include_in_plan BOOLEAN DEFAULT true;

ALTER TABLE migration_clusters
    ADD COLUMN IF NOT EXISTS exclude_reason TEXT;

-- Add manually_assigned to migration_vms so detection re-runs skip
-- VMs that were manually moved to a tenant via the reassign UI.
ALTER TABLE migration_vms
    ADD COLUMN IF NOT EXISTS manually_assigned BOOLEAN DEFAULT false;
