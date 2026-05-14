-- migrate_v1_99_0_tenant_health_scores.sql
-- Stores per-tenant composite health scores computed by the scheduler worker.
-- Score range: 0-100.  Components: snapshot_compliance, quota_headroom,
-- drift, sla_tier, tickets.  A score below 60 triggers an operational insight;
-- below 40 triggers a high-priority notification.

CREATE TABLE IF NOT EXISTS tenant_health_scores (
    project_id              TEXT        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    computed_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    score                   SMALLINT    NOT NULL CHECK (score BETWEEN 0 AND 100),
    snapshot_compliance     SMALLINT    NOT NULL DEFAULT 0,
    quota_headroom          SMALLINT    NOT NULL DEFAULT 0,
    drift                   SMALLINT    NOT NULL DEFAULT 0,
    sla_tier                SMALLINT    NOT NULL DEFAULT 0,
    tickets                 SMALLINT    NOT NULL DEFAULT 0,
    details                 JSONB       NOT NULL DEFAULT '{}',
    PRIMARY KEY (project_id, computed_at)
);

-- Partial index to quickly fetch the most-recent score per tenant
CREATE INDEX IF NOT EXISTS idx_tenant_health_scores_recent
    ON tenant_health_scores (project_id, computed_at DESC);

-- Handy view: latest score per tenant
CREATE OR REPLACE VIEW tenant_health_scores_latest AS
    SELECT DISTINCT ON (project_id)
        project_id,
        computed_at,
        score,
        snapshot_compliance,
        quota_headroom,
        drift,
        sla_tier,
        tickets,
        details
    FROM tenant_health_scores
    ORDER BY project_id, computed_at DESC;

INSERT INTO schema_migrations (filename, applied_at)
VALUES ('migrate_v1_99_0_tenant_health_scores.sql', NOW())
ON CONFLICT (filename) DO NOTHING;
