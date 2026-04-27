-- Migration v1.93.31: Add missing columns to *_history tables
-- These columns exist in the main tables but were absent from their history counterparts,
-- causing the _upsert_with_history savepoint to roll back every run (skipping history/drift).

ALTER TABLE hypervisors_history ADD COLUMN IF NOT EXISTS running_vms INTEGER;

ALTER TABLE volumes_history ADD COLUMN IF NOT EXISTS server_id TEXT;

ALTER TABLE networks_history ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE networks_history ADD COLUMN IF NOT EXISTS admin_state_up BOOLEAN;

ALTER TABLE subnets_history ADD COLUMN IF NOT EXISTS enable_dhcp BOOLEAN;
ALTER TABLE subnets_history ADD COLUMN IF NOT EXISTS ip_version INTEGER;

ALTER TABLE ports_history ADD COLUMN IF NOT EXISTS status TEXT;
