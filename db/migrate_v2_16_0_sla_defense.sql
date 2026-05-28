-- Migration v2.15.0 -> v2.16.0
-- Proactive SLA Defense Engine: schema for generated defense alerts.

CREATE TABLE IF NOT EXISTS sla_defense_alerts (
    id              SERIAL PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    sla_id          INT,
    insight_id      INT REFERENCES operational_insights(id) ON DELETE SET NULL,
    threat_type     TEXT NOT NULL,
    threat_detail   JSONB NOT NULL DEFAULT '{}'::jsonb,
    severity        TEXT NOT NULL CHECK (severity IN ('warning', 'critical')),
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'dismissed')),
    triggered_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    resolution_note TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_sla_defense_open_alert
    ON sla_defense_alerts(project_id, threat_type)
    WHERE status = 'open';

CREATE INDEX IF NOT EXISTS idx_sla_defense_status_triggered
    ON sla_defense_alerts(status, triggered_at DESC);

CREATE INDEX IF NOT EXISTS idx_sla_defense_project
    ON sla_defense_alerts(project_id);
