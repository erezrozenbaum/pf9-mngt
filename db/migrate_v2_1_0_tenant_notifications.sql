-- =====================================================================
-- Migration: v2.1.0 Tenant Notifications
-- Adds tenant notification subscription preferences table and
-- notification_target column to notification_log for operator/tenant routing
-- =====================================================================

-- ---------------------------------------------------------------------------
-- Column: notification_log.notification_target
-- 'operator' = admin-facing alert (existing behaviour, default)
-- 'tenant'   = tenant-facing event dispatched by tenant collectors
-- ---------------------------------------------------------------------------
ALTER TABLE notification_log
    ADD COLUMN IF NOT EXISTS notification_target TEXT NOT NULL DEFAULT 'operator';

CREATE INDEX IF NOT EXISTS idx_notification_log_target
    ON notification_log (notification_target);

-- ---------------------------------------------------------------------------
-- Table: tenant_notification_prefs
-- Per-user, per-project notification subscription preferences
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenant_notification_prefs (
    id               BIGSERIAL PRIMARY KEY,
    project_id       TEXT        NOT NULL,
    keystone_user_id TEXT        NOT NULL,
    event_type       TEXT        NOT NULL CHECK (event_type IN (
                         'snapshot_completed', 'snapshot_failed',
                         'restore_completed',  'restore_failed',
                         'quota_at_80pct',     'quota_at_95pct',
                         'vm_provisioned',     'vm_provision_failed',
                         'billing_invoice_ready')),
    channel          TEXT        NOT NULL CHECK (channel IN ('email', 'webhook')),
    endpoint         TEXT        NOT NULL,
    enabled          BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (project_id, keystone_user_id, event_type, channel)
);

CREATE INDEX IF NOT EXISTS idx_tnp_project ON tenant_notification_prefs (project_id);
CREATE INDEX IF NOT EXISTS idx_tnp_user    ON tenant_notification_prefs (keystone_user_id);
CREATE INDEX IF NOT EXISTS idx_tnp_event   ON tenant_notification_prefs (event_type);
