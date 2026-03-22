-- Phase 8: Migration Planner Normalization
-- ==========================================
-- Normalizes migration_projects to reference pf9_regions directly instead of
-- relying solely on ad-hoc pcd_auth_url / pcd_username credentials stored in
-- the project row.
--
-- When target_region_id is set, pcd-gap-analysis prefers the registered region's
-- credentials and capabilities JSONB for offline eligibility checks, falling back
-- to the stored pcd_auth_url / pcd_username / PF9_PASSWORD credentials if the
-- region is not registered.
--
-- source_region_id: nullable — the PCD region the workload is migrating FROM.
--   For VMware->PCD migrations this stays NULL. Relevant for PCD-to-PCD
--   cross-region migrations only.
--
-- target_region_id: nullable — the registered PCD region to provision INTO.
--   When set, pcd-gap-analysis uses the ClusterRegistry client for that region
--   rather than temporarily patching p9_common.CFG.
--
-- Both columns are NULLABLE: existing projects are unaffected. Legacy ad-hoc
-- credentials continue to work when target_region_id is NULL.

ALTER TABLE migration_projects
    ADD COLUMN IF NOT EXISTS source_region_id TEXT REFERENCES pf9_regions(id),
    ADD COLUMN IF NOT EXISTS target_region_id TEXT REFERENCES pf9_regions(id);

CREATE INDEX IF NOT EXISTS idx_migration_projects_source_region_id
    ON migration_projects (source_region_id)
    WHERE source_region_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_migration_projects_target_region_id
    ON migration_projects (target_region_id)
    WHERE target_region_id IS NOT NULL;

-- cluster_tasks: NOT_IMPLEMENTED guard row — ensures the table exists and
-- the status + task_type combination used by the stub check is indexed.
-- (cluster_tasks was created by migrate_multicluster.sql)
CREATE INDEX IF NOT EXISTS idx_cluster_tasks_pending
    ON cluster_tasks (status, created_at)
    WHERE status = 'pending';
