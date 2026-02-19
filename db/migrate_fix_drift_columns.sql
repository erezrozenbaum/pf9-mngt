-- migrate_fix_drift_columns.sql
-- Fix drift detection: add missing columns to tables so drift rules can match,
-- correct field_name mismatches in existing rules, and remove impossible rules.
-- Safe to run multiple times (IF NOT EXISTS / ON CONFLICT guards).

-- =====================================================================
-- 1. Add missing columns to resource tables
-- =====================================================================

-- networks: add status, admin_state_up
ALTER TABLE networks ADD COLUMN IF NOT EXISTS status         TEXT;
ALTER TABLE networks ADD COLUMN IF NOT EXISTS admin_state_up BOOLEAN;

-- ports: add status
ALTER TABLE ports ADD COLUMN IF NOT EXISTS status TEXT;

-- subnets: add enable_dhcp
ALTER TABLE subnets ADD COLUMN IF NOT EXISTS enable_dhcp BOOLEAN;

-- volumes: add server_id (first attached VM)
ALTER TABLE volumes ADD COLUMN IF NOT EXISTS server_id TEXT;

-- =====================================================================
-- 2. Back-fill new columns from raw_json already stored
-- =====================================================================

UPDATE networks SET status         = raw_json->>'status'
 WHERE status IS NULL AND raw_json->>'status' IS NOT NULL;

UPDATE networks SET admin_state_up = (raw_json->>'admin_state_up')::boolean
 WHERE admin_state_up IS NULL AND raw_json->>'admin_state_up' IS NOT NULL;

UPDATE ports    SET status         = raw_json->>'status'
 WHERE status IS NULL AND raw_json->>'status' IS NOT NULL;

UPDATE subnets  SET enable_dhcp    = (raw_json->>'enable_dhcp')::boolean
 WHERE enable_dhcp IS NULL AND raw_json->>'enable_dhcp' IS NOT NULL;

UPDATE volumes  SET server_id = raw_json->'attachments'->0->>'server_id'
 WHERE server_id IS NULL
   AND jsonb_array_length(COALESCE(raw_json->'attachments', '[]'::jsonb)) > 0;

-- =====================================================================
-- 3. Fix drift-rule field_name mismatches
-- =====================================================================

-- volumes.size  → size_gb  (column is called size_gb, not size)
UPDATE drift_rules SET field_name = 'size_gb',
                       description = 'Volume size changed — possible extend'
 WHERE resource_type = 'volumes' AND field_name = 'size';

-- networks.shared → is_shared (column is called is_shared)
UPDATE drift_rules SET field_name = 'is_shared',
                       description = 'Network sharing setting changed'
 WHERE resource_type = 'networks' AND field_name = 'shared';

-- snapshots.size → size_gb
UPDATE drift_rules SET field_name = 'size_gb',
                       description = 'Snapshot size changed'
 WHERE resource_type = 'snapshots' AND field_name = 'size';

-- servers.host_id → remove (no such column; hypervisor_hostname already covers this)
DELETE FROM drift_rules
 WHERE resource_type = 'servers' AND field_name = 'host_id';

-- =====================================================================
-- 4. Add indexes on new columns for query performance
-- =====================================================================
CREATE INDEX IF NOT EXISTS idx_networks_status       ON networks(status);
CREATE INDEX IF NOT EXISTS idx_ports_status           ON ports(status);
CREATE INDEX IF NOT EXISTS idx_volumes_server_id      ON volumes(server_id);
