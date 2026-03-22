-- =============================================================================
-- migrate_phase5_workers.sql - Phase 5: Multi-Region Worker Prerequisites
-- =============================================================================
-- Applied automatically at API startup via startup_event() in api/main.py.
-- Fully idempotent: safe to run multiple times.
-- Run with: psql -v ON_ERROR_STOP=0 -f migrate_phase5_workers.sql
--
-- Changes:
--   1. snapshot_runs.region_id         - tags each snapshot run with its region
--   2. snapshot_runs index on region_id - query performance
--
-- Note: snapshot_records.region_id and snapshot_policy_sets.region_id are
-- already present from migrate_multicluster.sql.
-- cluster_sync_metrics table is created in db/init.sql (Phase 1).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. snapshot_runs: add region_id for Phase 5 multi-region tracking
-- ---------------------------------------------------------------------------
ALTER TABLE snapshot_runs
    ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);

CREATE INDEX IF NOT EXISTS idx_snapshot_runs_region_id
    ON snapshot_runs(region_id);
