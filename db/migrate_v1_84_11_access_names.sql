-- ---------------------------------------------------------------------------
-- Migration v1.84.11 — Add user_name and tenant_name to tenant_portal_access
--
-- Run against: local Docker   → Get-Content db/migrate_v1_84_11_access_names.sql | docker exec -i pf9_db psql -U pf9 -d pf9_mgmt
--              Kubernetes      → Get-Content db/migrate_v1_84_11_access_names.sql | kubectl exec -i -n pf9-mngt pf9-db-0 -- psql -U pf9 -d pf9_mgmt
-- Idempotent: ADD COLUMN IF NOT EXISTS is safe to re-run.
-- ---------------------------------------------------------------------------

ALTER TABLE tenant_portal_access
    ADD COLUMN IF NOT EXISTS user_name   TEXT,   -- friendly display name for the Keystone user
    ADD COLUMN IF NOT EXISTS tenant_name TEXT;   -- friendly display name for the tenant / org

-- Confirm
SELECT column_name, data_type
FROM   information_schema.columns
WHERE  table_name = 'tenant_portal_access'
  AND  column_name IN ('user_name', 'tenant_name')
ORDER  BY column_name;
