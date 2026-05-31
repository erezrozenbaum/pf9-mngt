-- Migration v2.16.x -> v2.17.0 (partial)
-- Adds operational maintenance window suppression table
-- and security_posture component storage for tenant health scores.

CREATE TABLE IF NOT EXISTS ops_maintenance_windows (
    id                      SERIAL PRIMARY KEY,
    title                   TEXT NOT NULL,
    starts_at               TIMESTAMPTZ NOT NULL,
    ends_at                 TIMESTAMPTZ NOT NULL,
    scope                   JSONB,
    suppress_clea           BOOLEAN NOT NULL DEFAULT true,
    suppress_sla_defense    BOOLEAN NOT NULL DEFAULT true,
    suppress_notifications  BOOLEAN NOT NULL DEFAULT false,
    created_by              TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_ops_maintenance_window_order CHECK (ends_at > starts_at)
);

CREATE INDEX IF NOT EXISTS idx_ops_maintenance_active
    ON ops_maintenance_windows(starts_at, ends_at);

ALTER TABLE tenant_health_scores
    ADD COLUMN IF NOT EXISTS security_posture SMALLINT NOT NULL DEFAULT 0;

DROP VIEW IF EXISTS tenant_health_scores_latest;

CREATE VIEW tenant_health_scores_latest AS
    SELECT DISTINCT ON (project_id)
        project_id,
        computed_at,
        score,
        snapshot_compliance,
        quota_headroom,
        drift,
        sla_tier,
        tickets,
        security_posture,
        details
    FROM tenant_health_scores
    ORDER BY project_id, computed_at DESC;

INSERT INTO system_settings (key, value, description)
VALUES
    ('health_score.weight.snapshot_compliance', '22', 'Max points for snapshot compliance component (0-100 range)'),
    ('health_score.weight.quota_headroom',      '18', 'Max points for quota headroom component'),
    ('health_score.weight.drift',               '18', 'Max points for drift component'),
    ('health_score.weight.sla_tier',            '17', 'Max points for SLA tier component'),
    ('health_score.weight.tickets',             '10', 'Max points for tickets component'),
    ('health_score.weight.security_posture',    '15', 'Max points for security posture component')
ON CONFLICT (key) DO NOTHING;

INSERT INTO schema_migrations (filename, applied_at)
VALUES ('migrate_v2_17_0_maintenance_health.sql', NOW())
ON CONFLICT (filename) DO NOTHING;
