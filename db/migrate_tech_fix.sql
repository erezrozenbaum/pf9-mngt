-- Migration: Tech Fix Time scoring system
-- Phase 5.0 — Per-VM post-migration fix time estimation
-- Idempotent: safe to re-run

-- Per-VM manual override for tech fix time
ALTER TABLE migration_vms ADD COLUMN IF NOT EXISTS tech_fix_minutes_override INTEGER DEFAULT NULL;

-- Per-project fix time scoring settings
CREATE TABLE IF NOT EXISTS migration_fix_settings (
    id                      SERIAL PRIMARY KEY,
    project_id              TEXT NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,

    -- Per-factor weights (minutes added to fix estimate per VM)
    weight_windows          INTEGER NOT NULL DEFAULT 20,
    weight_extra_volume     INTEGER NOT NULL DEFAULT 15,
    weight_extra_nic        INTEGER NOT NULL DEFAULT 10,
    weight_cold_mode        INTEGER NOT NULL DEFAULT 15,
    weight_risk_yellow      INTEGER NOT NULL DEFAULT 15,
    weight_risk_red         INTEGER NOT NULL DEFAULT 25,
    weight_has_snapshots    INTEGER NOT NULL DEFAULT 10,
    weight_cross_tenant_dep INTEGER NOT NULL DEFAULT 15,
    weight_unknown_os       INTEGER NOT NULL DEFAULT 20,

    -- Per-OS-family expected fix rates (fraction of VMs that will actually need a fix)
    fix_rate_windows        NUMERIC(4,2) NOT NULL DEFAULT 0.50,
    fix_rate_linux          NUMERIC(4,2) NOT NULL DEFAULT 0.20,
    fix_rate_other          NUMERIC(4,2) NOT NULL DEFAULT 0.40,

    -- Optional global fix rate override; when set, overrides per-OS rates
    fix_rate_global         NUMERIC(4,2) DEFAULT NULL,

    -- Cutover window assumed per VM (minutes of downtime for final sync + first boot)
    cutover_minutes         INTEGER NOT NULL DEFAULT 30,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(project_id)
);

COMMENT ON TABLE migration_fix_settings IS
    'Per-project weights and fix rates for post-migration technical fix time estimation';
COMMENT ON COLUMN migration_fix_settings.fix_rate_global IS
    'When set, all OS families use this rate instead of the per-family rates';
COMMENT ON COLUMN migration_fix_settings.cutover_minutes IS
    'Downtime window per VM for final sync + first boot (separate from data-copy time)';
