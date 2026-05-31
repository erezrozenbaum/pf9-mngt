-- Migration v2.18.0
-- Copilot AI triage runtime configuration fields.

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'copilot_config'
  ) THEN
    ALTER TABLE copilot_config
      ADD COLUMN IF NOT EXISTS ai_triage_enabled BOOLEAN NOT NULL DEFAULT false,
      ADD COLUMN IF NOT EXISTS ai_triage_min_severity TEXT NOT NULL DEFAULT 'critical',
      ADD COLUMN IF NOT EXISTS ai_triage_max_per_hour INTEGER NOT NULL DEFAULT 10,
      ADD COLUMN IF NOT EXISTS ai_triage_notify_email BOOLEAN NOT NULL DEFAULT false;
  END IF;
END $$;

INSERT INTO schema_migrations (filename, applied_at)
VALUES ('migrate_v2_18_0_copilot_triage_config.sql', NOW())
ON CONFLICT (filename) DO NOTHING;
