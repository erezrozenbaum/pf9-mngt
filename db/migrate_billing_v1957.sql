-- v1.95.7: Grant SELECT on domains and metering_snapshots to tenant_portal_role
-- Required for tenant portal billing-aware chargeback endpoint

GRANT SELECT ON domains TO tenant_portal_role;
GRANT SELECT ON metering_snapshots TO tenant_portal_role;
