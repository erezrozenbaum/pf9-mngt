-- Migration Planner v1.31.2: Cohort schedule fields + target_project_name fix
-- Idempotent: safe to run multiple times

-- 1. Add per-cohort schedule override fields
ALTER TABLE migration_cohorts
    ADD COLUMN IF NOT EXISTS schedule_duration_days INTEGER,
    ADD COLUMN IF NOT EXISTS target_vms_per_day INTEGER;

-- 2. Fix target_project_name: for vCloud tenants it should be org_vdc, not tenant_name.
--    Only fix rows where target_project_name = target_domain_name (i.e. auto-seeded wrong)
--    AND org_vdc is set (it's a vCloud environment where OrgVDC maps to PCD project).
UPDATE migration_tenants
SET target_project_name = org_vdc
WHERE org_vdc IS NOT NULL
  AND org_vdc != ''
  AND target_confirmed = false;   -- do not touch rows the operator already confirmed

-- 3. Backfill vlan_id in network mappings where it can be parsed from source_network_name
UPDATE migration_network_mappings
SET vlan_id = CAST(
    NULLIF(substring(source_network_name from '[Vv][Ll][Aa][Nn][_-]?([0-9]+)'), '')
    AS INTEGER
)
WHERE vlan_id IS NULL
  AND source_network_name ~ '[Vv][Ll][Aa][Nn][_-]?[0-9]+';
