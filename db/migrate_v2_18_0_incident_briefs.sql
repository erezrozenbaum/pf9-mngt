-- Migration v2.18.0
-- AI Incident Triage: persistent incident brief records.

CREATE TABLE IF NOT EXISTS incident_briefs (
    id                  SERIAL PRIMARY KEY,
    event_id            BIGINT REFERENCES operational_events(id) ON DELETE CASCADE,
    event_type          TEXT NOT NULL,
    entity_name         TEXT,
    project_id          TEXT,
    project_name        TEXT,
    analysis            TEXT NOT NULL,
    recommendation      TEXT NOT NULL,
    risk_level          TEXT NOT NULL DEFAULT 'medium' CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    runbook_name        TEXT,
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at        TIMESTAMPTZ,
    dismissed_by        TEXT,
    dismissed_at        TIMESTAMPTZ,
    executed_runbook_id BIGINT REFERENCES runbook_executions(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_incident_briefs_generated
    ON incident_briefs(generated_at DESC);

CREATE INDEX IF NOT EXISTS idx_incident_briefs_event
    ON incident_briefs(event_id);

CREATE INDEX IF NOT EXISTS idx_incident_briefs_project
    ON incident_briefs(project_id, generated_at DESC);

CREATE INDEX IF NOT EXISTS idx_incident_briefs_open
    ON incident_briefs(generated_at DESC)
    WHERE dismissed_at IS NULL AND executed_runbook_id IS NULL;

INSERT INTO schema_migrations (filename, applied_at)
VALUES ('migrate_v2_18_0_incident_briefs.sql', NOW())
ON CONFLICT (filename) DO NOTHING;
