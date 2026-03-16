-- Migration: Add container_alert_email to app_settings
-- Idempotent — safe to run multiple times.
-- This key stores the email address that receives container health alerts
-- from the pf9_monitoring container watchdog.

INSERT INTO app_settings (key, value)
VALUES ('container_alert_email', '')
ON CONFLICT (key) DO NOTHING;
