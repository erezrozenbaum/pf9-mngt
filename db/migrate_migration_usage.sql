-- Migration: Add usage metrics, OS version, network name to migration planner
-- Phase 1.4 — Usage-aware migration assessment
-- Idempotent: safe to re-run

-- migration_vms: Add provisioned/in-use columns (were inserted by routes but missing from schema)
ALTER TABLE migration_vms ADD COLUMN IF NOT EXISTS provisioned_mb   BIGINT DEFAULT 0;
ALTER TABLE migration_vms ADD COLUMN IF NOT EXISTS in_use_mb        BIGINT DEFAULT 0;

-- migration_vms: Add computed in_use_gb from vPartition (actual used disk space)
ALTER TABLE migration_vms ADD COLUMN IF NOT EXISTS in_use_gb        NUMERIC(12,2) DEFAULT 0;

-- migration_vms: OS version (full string from RVTools, e.g. "Microsoft Windows Server 2019 (64-bit)")
ALTER TABLE migration_vms ADD COLUMN IF NOT EXISTS os_version       TEXT;

-- migration_vms: Primary network name (aggregated from first NIC)
ALTER TABLE migration_vms ADD COLUMN IF NOT EXISTS network_name     TEXT;

-- migration_vm_disks: Add consumed space per disk (from vPartition join)
ALTER TABLE migration_vm_disks ADD COLUMN IF NOT EXISTS consumed_gb NUMERIC(12,2);

-- migration_vms: Partition-based used disk (sum of all consumed partition space)
-- Stored separately from in_use_mb (which comes from vInfo) for clarity
ALTER TABLE migration_vms ADD COLUMN IF NOT EXISTS partition_used_gb NUMERIC(12,2) DEFAULT 0;

-- Also update the master CREATE TABLE in migrate_migration_planner.sql
-- to include these columns for fresh installs (done via code edit, not this SQL)
