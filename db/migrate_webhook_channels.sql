-- =====================================================================
-- Migration: Webhook notification channels (Slack / Microsoft Teams)
-- Adds placeholder rows to notification_channels for Slack and Teams.
-- Webhook URLs are supplied via SLACK_WEBHOOK_URL / TEAMS_WEBHOOK_URL
-- environment variables — no secret is stored in the database.
-- =====================================================================

INSERT INTO notification_channels (channel_type, name, enabled, config)
SELECT 'slack', 'Slack Incoming Webhook', false,
       '{"note": "Set SLACK_WEBHOOK_URL env var to enable"}'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM notification_channels
    WHERE channel_type = 'slack' AND name = 'Slack Incoming Webhook'
);

INSERT INTO notification_channels (channel_type, name, enabled, config)
SELECT 'teams', 'Microsoft Teams Webhook', false,
       '{"note": "Set TEAMS_WEBHOOK_URL env var to enable"}'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM notification_channels
    WHERE channel_type = 'teams' AND name = 'Microsoft Teams Webhook'
);
