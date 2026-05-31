-- Migration v2.17.1
-- Adds inbound PSA sync capabilities to psa_webhook_config and
-- grants read access for the intelligence worker role.

ALTER TABLE psa_webhook_config
    ADD COLUMN IF NOT EXISTS inbound_enabled BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS inbound_token TEXT,
    ADD COLUMN IF NOT EXISTS status_map JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pf9_intelligence_svc') THEN
    GRANT SELECT ON psa_webhook_config TO pf9_intelligence_svc;
  END IF;
END $$;

INSERT INTO schema_migrations (filename, applied_at)
VALUES ('migrate_v2_17_1_psa_inbound.sql', NOW())
ON CONFLICT (filename) DO NOTHING;
