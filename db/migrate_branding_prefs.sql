-- Migration: Add app_settings (branding) and user_preferences (tab order) tables
-- Idempotent — safe to run multiple times on existing databases.

-- App-wide settings / branding
CREATE TABLE IF NOT EXISTS app_settings (
    key           TEXT PRIMARY KEY,
    value         TEXT NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by    TEXT
);

INSERT INTO app_settings (key, value) VALUES
    ('company_name', 'PF9 Management System'),
    ('company_subtitle', 'Platform9 Infrastructure Management'),
    ('login_hero_title', 'Welcome to PF9 Management'),
    ('login_hero_description', 'Comprehensive Platform9 infrastructure management with real-time monitoring, snapshot automation, security group management, and full restore capabilities.'),
    ('login_hero_features', '["Real-time VM & infrastructure monitoring","Automated snapshot policies & compliance","Security group management with human-readable rules","One-click snapshot restore with storage cleanup","RBAC with LDAP authentication","Full audit trail & history tracking"]'),
    ('company_logo_url', ''),
    ('primary_color', '#667eea'),
    ('secondary_color', '#764ba2')
ON CONFLICT (key) DO NOTHING;

-- Per-user preferences (tab order, etc.)
CREATE TABLE IF NOT EXISTS user_preferences (
    username      TEXT NOT NULL,
    pref_key      TEXT NOT NULL,
    pref_value    TEXT NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (username, pref_key)
);
