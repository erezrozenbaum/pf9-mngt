-- =============================================================================
-- Migration v2.2.1 — Grant tenant_portal_role access to tenant_notification_prefs
--
-- The tenant_notification_prefs table was added in v2.1.0 but its GRANT to
-- tenant_portal_role was accidentally omitted, causing every Notification
-- Settings request in the tenant portal to fail with HTTP 500.
-- =============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_notification_prefs TO tenant_portal_role;

INSERT INTO schema_migrations (filename, applied_at)
VALUES ('migrate_v2_2_1_notification_grant.sql', NOW())
ON CONFLICT (filename) DO NOTHING;
