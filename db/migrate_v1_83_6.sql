-- ============================================================
-- Migration v1.83.6 — vm_provisioning_batches region_id column
-- ============================================================
-- Applies to environments where vm_provisioning_batches was
-- created by the API before migrate_multicluster.sql ran (so the
-- DO-block guard in that migration skipped the ALTER).
--
-- Safe on all environments:
--   - Column already present   → IF NOT EXISTS is a no-op
--   - Table doesn't exist yet  → DO block skips silently
--   - Table exists, col absent → column is added
-- ============================================================

DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_name = 'vm_provisioning_batches' AND table_schema = 'public'
  ) THEN
    ALTER TABLE vm_provisioning_batches
      ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
  END IF;
END $$;
