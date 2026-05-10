-- v1.95.13: Intelligence Views — Metering & Growth Enhancements
-- Adds a pre-aggregated monthly-per-tenant summary table that stores
-- resource totals and computed costs for each calendar month.
-- Written by metering_worker on first collection of each month (UPSERT).
-- Read by /api/sla/portfolio/summary and /api/sla/portfolio/fleet-metering.

CREATE TABLE IF NOT EXISTS portfolio_metering_monthly (
    tenant_id          TEXT    NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    month              DATE    NOT NULL,  -- first day of month (YYYY-MM-01)
    -- Allocated resources (from metering_resources, averaged over the month)
    avg_vcpus          NUMERIC(10,2) NOT NULL DEFAULT 0,
    avg_ram_gb         NUMERIC(10,2) NOT NULL DEFAULT 0,
    avg_disk_gb        NUMERIC(10,2) NOT NULL DEFAULT 0,
    -- Peak resources
    peak_vcpus         INTEGER NOT NULL DEFAULT 0,
    peak_ram_gb        NUMERIC(10,2) NOT NULL DEFAULT 0,
    -- Quota snapshot at end of month (from project_quotas)
    quota_vcpu_limit   INTEGER,
    quota_vcpu_used    INTEGER,
    quota_ram_limit_mb INTEGER,
    quota_ram_used_mb  INTEGER,
    quota_storage_limit_gb INTEGER,
    quota_storage_used_gb  NUMERIC(10,2),
    -- Estimated cost (metering_config rates × allocated resources × hours)
    estimated_cost     NUMERIC(14,4) NOT NULL DEFAULT 0,
    currency           TEXT    NOT NULL DEFAULT 'USD',
    -- Number of distinct VMs seen this month
    vm_count           INTEGER NOT NULL DEFAULT 0,
    computed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, month)
);

CREATE INDEX IF NOT EXISTS idx_pmm_tenant_month
    ON portfolio_metering_monthly(tenant_id, month DESC);
CREATE INDEX IF NOT EXISTS idx_pmm_month
    ON portfolio_metering_monthly(month DESC);

-- RBAC: allow admin/superadmin to read this table (used via API only)
DO $$
BEGIN
    -- No direct RBAC rows needed — access is gate-kept by the API endpoint
    -- using the existing 'sla:read' permission.
    NULL;
END $$;
