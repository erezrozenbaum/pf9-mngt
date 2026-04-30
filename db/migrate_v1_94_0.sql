-- v1.94.0: Dashboard health trend — daily snapshot table
-- Stores one row per calendar day with aggregate VM / host / alert counts.
-- Written by pf9_scheduler_worker (UPSERT on snapshot_date) so missed days
-- back-fill naturally on the next scheduler run.
-- The /dashboard/health-trend endpoint reads the last N days for sparkline charts.

CREATE TABLE IF NOT EXISTS dashboard_health_snapshots (
    id             BIGSERIAL PRIMARY KEY,
    snapshot_date  DATE        NOT NULL UNIQUE,
    total_vms      INTEGER     NOT NULL DEFAULT 0,
    running_vms    INTEGER     NOT NULL DEFAULT 0,
    total_hosts    INTEGER     NOT NULL DEFAULT 0,
    critical_count INTEGER     NOT NULL DEFAULT 0,
    recorded_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dashboard_health_snapshots_date
    ON dashboard_health_snapshots(snapshot_date DESC);
