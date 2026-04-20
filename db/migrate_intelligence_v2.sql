-- migrate_intelligence_v2.sql
-- Phase 2: insight_recommendations table
-- Run once: psql $DATABASE_URL < db/migrate_intelligence_v2.sql

-- Executable recommendations attached to insights.
-- action_type: runbook | ticket | cleanup | resize | migrate
CREATE TABLE IF NOT EXISTS insight_recommendations (
    id               SERIAL PRIMARY KEY,
    insight_id       INT NOT NULL REFERENCES operational_insights(id) ON DELETE CASCADE,
    action_type      TEXT NOT NULL,
    runbook_id       INT REFERENCES runbooks(id),
    action_payload   JSONB NOT NULL DEFAULT '{}',
    estimated_impact TEXT,
    status           TEXT NOT NULL DEFAULT 'pending', -- pending | executed | dismissed
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    executed_at      TIMESTAMPTZ,
    execution_id     INT REFERENCES runbook_executions(id)
);

CREATE INDEX IF NOT EXISTS idx_recs_insight ON insight_recommendations(insight_id);
CREATE INDEX IF NOT EXISTS idx_recs_status  ON insight_recommendations(status);
