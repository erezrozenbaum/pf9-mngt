-- MIGRATION: Snapshot chain tracking (v2.3.0)
-- Adds parent_snapshot_id linkage to snapshot_records so full chains
-- (base → incremental → incremental → ...) can be traversed, and
-- a pre-delete safety hook that rejects deletion of any snapshot that
-- has dependents still present.

-- Step 1: Add parent linkage column to snapshot_records
-- Note: snapshot_id is nullable, so we store the parent snapshot_id as plain TEXT.
-- Application code enforces chain integrity; the DB trigger below prevents
-- deletion of parent snapshots that still have children.
ALTER TABLE snapshot_records
    ADD COLUMN IF NOT EXISTS parent_snapshot_id TEXT;

-- Step 2: Chain-depth column (0 = base / full snapshot, 1+ = incremental)
ALTER TABLE snapshot_records
    ADD COLUMN IF NOT EXISTS chain_depth INTEGER NOT NULL DEFAULT 0;

-- Step 3: Chain root reference for fast retrieval of the full chain
ALTER TABLE snapshot_records
    ADD COLUMN IF NOT EXISTS chain_root_snapshot_id TEXT;

-- Step 4: Index for chain traversal
CREATE INDEX IF NOT EXISTS idx_snapshot_records_parent
    ON snapshot_records(parent_snapshot_id);

CREATE INDEX IF NOT EXISTS idx_snapshot_records_chain_root
    ON snapshot_records(chain_root_snapshot_id);

-- Step 5: Snapshot chain policies table
CREATE TABLE IF NOT EXISTS snapshot_chain_policies (
    id              BIGSERIAL PRIMARY KEY,
    project_id      TEXT NOT NULL,
    volume_id       TEXT NOT NULL,
    max_chain_depth INTEGER NOT NULL DEFAULT 5,   -- max incrementals before a new base
    auto_rebase     BOOLEAN NOT NULL DEFAULT true, -- create new base when chain is too deep
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, volume_id)
);

CREATE INDEX IF NOT EXISTS idx_snapshot_chain_policies_project
    ON snapshot_chain_policies(project_id);

-- Step 6: Pre-delete safety function
-- Prevents deleting a snapshot that still has child snapshots.
CREATE OR REPLACE FUNCTION prevent_snapshot_chain_break()
RETURNS TRIGGER AS $$
DECLARE
    child_count INTEGER;
BEGIN
    -- Check if any other snapshot_records reference this one as their parent
    SELECT COUNT(*)
      INTO child_count
      FROM snapshot_records
     WHERE parent_snapshot_id = OLD.snapshot_id
       AND status <> 'deleted'
       AND id <> OLD.id;

    IF child_count > 0 THEN
        RAISE EXCEPTION
            'Cannot delete snapshot % — it has % dependent child snapshot(s). '
            'Delete child snapshots first or mark them deleted.',
            OLD.snapshot_id, child_count
            USING ERRCODE = '23503';  -- foreign_key_violation
    END IF;

    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

-- Attach the trigger (DROP first so migration is re-runnable)
DROP TRIGGER IF EXISTS trg_prevent_snapshot_chain_break ON snapshot_records;

CREATE TRIGGER trg_prevent_snapshot_chain_break
    BEFORE DELETE ON snapshot_records
    FOR EACH ROW
    EXECUTE FUNCTION prevent_snapshot_chain_break();

-- Record migration
INSERT INTO schema_migrations (filename, applied_at)
VALUES ('migrate_v2_3_0_snapshot_chains.sql', NOW())
ON CONFLICT (filename) DO NOTHING;
