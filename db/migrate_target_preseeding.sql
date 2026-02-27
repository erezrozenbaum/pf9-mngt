-- Migration Planner v1.31.1: Target name pre-seeding + confirmed flags
-- Rationale: target network / domain / project names default to the source name
-- ("best guess, confirm or override") instead of blank. A `confirmed` flag
-- distinguishes auto-seeded rows (needs review) from user-confirmed rows.
-- This is idempotent — safe to re-run.

-- ── network_mappings: add confirmed flag ─────────────────────────────────────
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'migration_network_mappings' AND column_name = 'confirmed'
  ) THEN
    ALTER TABLE migration_network_mappings
      ADD COLUMN confirmed BOOLEAN NOT NULL DEFAULT false;
    -- Existing rows that already have a non-empty target were manually set → confirm them
    UPDATE migration_network_mappings
       SET confirmed = true
     WHERE target_network_name IS NOT NULL AND target_network_name != '';
  END IF;
END $$;

-- ── migration_tenants: add target_confirmed flag + pre-seed target names ─────
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'migration_tenants' AND column_name = 'target_confirmed'
  ) THEN
    ALTER TABLE migration_tenants
      ADD COLUMN target_confirmed BOOLEAN NOT NULL DEFAULT false;
    -- Existing rows that already have a non-empty target domain were manually set → confirm them
    UPDATE migration_tenants
       SET target_confirmed = true
     WHERE target_domain_name IS NOT NULL AND target_domain_name != '';
  END IF;
END $$;

-- Pre-seed target_domain_name / target_project_name from tenant_name for any
-- rows where they are still NULL (idempotent — only fills blanks, never overwrites)
UPDATE migration_tenants
   SET target_domain_name  = tenant_name,
       target_project_name = tenant_name,
       target_confirmed     = false
 WHERE (target_domain_name IS NULL OR target_domain_name = '')
   AND (target_project_name IS NULL OR target_project_name = '');
