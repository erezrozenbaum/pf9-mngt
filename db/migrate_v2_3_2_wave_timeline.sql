-- Migration v2.3.2: Wave execution timeline and SLA migration tracking
--
-- 1. Add started_at / completed_at timestamps to migration_waves so that
--    per-wave execution duration is visible in the UI and included in QBR
--    and SLA reports.
-- 2. Add migrations_completed counter to sla_compliance_monthly for the
--    monthly SLA worker rollup.

-- ── migration_waves ────────────────────────────────────────────────────────
ALTER TABLE migration_waves
    ADD COLUMN IF NOT EXISTS started_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;

-- ── sla_compliance_monthly ─────────────────────────────────────────────────
ALTER TABLE sla_compliance_monthly
    ADD COLUMN IF NOT EXISTS migrations_completed INTEGER NOT NULL DEFAULT 0;
