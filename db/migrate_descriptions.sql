-- v1.31.7: Add target_domain_description to migration_tenants
-- target_display_name = project description (already exists)
-- target_domain_description = domain description (new)

ALTER TABLE migration_tenants ADD COLUMN IF NOT EXISTS target_domain_description TEXT;
