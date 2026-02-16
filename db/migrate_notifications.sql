-- =====================================================================
-- Migration: Email Notification System
-- Adds notification preferences, channels, and log tables
-- =====================================================================

-- ---------------------------------------------------------------------------
-- Table: notification_channels
-- Stores SMTP / channel configurations (secrets stay in env vars)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notification_channels (
    id              SERIAL PRIMARY KEY,
    channel_type    TEXT NOT NULL DEFAULT 'email',          -- email | slack | webhook (future)
    name            TEXT NOT NULL,
    enabled         BOOLEAN NOT NULL DEFAULT true,
    config          JSONB NOT NULL DEFAULT '{}',            -- non-secret config (from_name, etc.)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed a default email channel
INSERT INTO notification_channels (channel_type, name, enabled, config)
VALUES ('email', 'Default SMTP', true, '{"from_name": "Platform9 Management"}')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- Table: notification_preferences
-- Per-user subscription to specific event types
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notification_preferences (
    id              SERIAL PRIMARY KEY,
    username        TEXT NOT NULL,
    email           TEXT NOT NULL,
    event_type      TEXT NOT NULL,          -- drift_critical, drift_warning, snapshot_failure,
                                            -- compliance_violation, health_score_drop, auth_alert
    severity_min    TEXT NOT NULL DEFAULT 'warning',  -- minimum severity to trigger: info | warning | critical
    delivery_mode   TEXT NOT NULL DEFAULT 'immediate', -- immediate | digest
    enabled         BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (username, event_type)
);

-- ---------------------------------------------------------------------------
-- Table: notification_log
-- Tracks every notification sent, with deduplication
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notification_log (
    id              SERIAL PRIMARY KEY,
    username        TEXT NOT NULL,
    email           TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    event_id        TEXT,                    -- source event id for dedup
    dedup_key       TEXT,                    -- hash(event_type + resource_id + event_id)
    subject         TEXT NOT NULL,
    body_preview    TEXT,                    -- first 200 chars of body
    delivery_status TEXT NOT NULL DEFAULT 'pending',  -- pending | sent | failed | skipped
    error_message   TEXT,
    sent_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_notification_log_username   ON notification_log (username);
CREATE INDEX IF NOT EXISTS idx_notification_log_event_type ON notification_log (event_type);
CREATE INDEX IF NOT EXISTS idx_notification_log_dedup_key  ON notification_log (dedup_key);
CREATE INDEX IF NOT EXISTS idx_notification_log_created_at ON notification_log (created_at DESC);

-- ---------------------------------------------------------------------------
-- Table: notification_digests
-- Tracks digest batching state per user
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notification_digests (
    id              SERIAL PRIMARY KEY,
    username        TEXT NOT NULL,
    email           TEXT NOT NULL,
    events_json     JSONB NOT NULL DEFAULT '[]',   -- accumulated events for next digest
    last_sent_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (username)
);

-- ---------------------------------------------------------------------------
-- Indexes for preference lookups
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_notification_prefs_username ON notification_preferences (username);
CREATE INDEX IF NOT EXISTS idx_notification_prefs_event    ON notification_preferences (event_type);

-- ---------------------------------------------------------------------------
-- RBAC: Notification permissions for all roles
-- ---------------------------------------------------------------------------
INSERT INTO role_permissions (role, resource, action) VALUES
-- All roles can read their own notification preferences
('viewer', 'notifications', 'read'),
('viewer', 'notifications', 'write'),
('operator', 'notifications', 'read'),
('operator', 'notifications', 'write'),
('admin', 'notifications', 'admin'),
('superadmin', 'notifications', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;
