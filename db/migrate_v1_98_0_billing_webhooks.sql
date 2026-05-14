-- migrate_v1_98_0_billing_webhooks.sql
-- Create billing_webhooks table for webhook registration endpoints.
-- Supports event-driven billing integrations with SSRF-guarded URL registration.

CREATE TABLE IF NOT EXISTS billing_webhooks (
    id              SERIAL PRIMARY KEY,
    tenant_id       VARCHAR(255) NOT NULL,
    webhook_url     TEXT        NOT NULL,
    event_types     JSONB       NOT NULL DEFAULT '[]',
    secret_token    TEXT,
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    last_success    TIMESTAMPTZ,
    failure_count   INTEGER     NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_billing_webhooks_tenant_id
    ON billing_webhooks (tenant_id);

CREATE INDEX IF NOT EXISTS idx_billing_webhooks_active
    ON billing_webhooks (is_active)
    WHERE is_active = TRUE;

INSERT INTO schema_migrations (filename, applied_at)
VALUES ('migrate_v1_98_0_billing_webhooks.sql', NOW())
ON CONFLICT (filename) DO NOTHING;
