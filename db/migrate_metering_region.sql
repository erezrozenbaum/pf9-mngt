-- =====================================================================
-- Migration: Add region_id to metering and backup tables
-- Phase 5: Multi-region worker support
-- =====================================================================

-- Metering tables: tag every row with the region it was collected from.
-- NULL = pre-migration rows collected before multi-region was enabled.
ALTER TABLE metering_resources  ADD COLUMN IF NOT EXISTS region_id TEXT;
ALTER TABLE metering_snapshots  ADD COLUMN IF NOT EXISTS region_id TEXT;
ALTER TABLE metering_restores   ADD COLUMN IF NOT EXISTS region_id TEXT;
ALTER TABLE metering_quotas     ADD COLUMN IF NOT EXISTS region_id TEXT;
ALTER TABLE metering_efficiency ADD COLUMN IF NOT EXISTS region_id TEXT;

-- Backup history: track which region triggered a manual backup request.
-- NULL for scheduled / infrastructure-level backups (they cover the shared DB).
ALTER TABLE backup_history ADD COLUMN IF NOT EXISTS region_id TEXT;

-- Indexes for region-scoped queries in dashboards and smart-queries.
CREATE INDEX IF NOT EXISTS idx_metering_resources_region
    ON metering_resources (region_id, collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_metering_snapshots_region
    ON metering_snapshots (region_id, collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_metering_restores_region
    ON metering_restores (region_id, collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_metering_quotas_region
    ON metering_quotas (region_id, collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_metering_efficiency_region
    ON metering_efficiency (region_id, collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_backup_history_region
    ON backup_history (region_id) WHERE region_id IS NOT NULL;
