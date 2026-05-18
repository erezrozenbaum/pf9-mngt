-- migrate_v2_3_0_health_score_config.sql
-- Adds health_score_weights to system_settings (superadmin-editable).
-- Adds health_score_disabled column to projects (per-tenant opt-out).

-- Health score component weights (must sum to 100)
INSERT INTO system_settings (key, value, description)
VALUES
  ('health_score.weight.snapshot_compliance', '25', 'Max points for snapshot compliance component (0-100 range)'),
  ('health_score.weight.quota_headroom',      '20', 'Max points for quota headroom component'),
  ('health_score.weight.drift',               '20', 'Max points for drift component'),
  ('health_score.weight.sla_tier',            '20', 'Max points for SLA tier component'),
  ('health_score.weight.tickets',             '15', 'Max points for tickets component')
ON CONFLICT (key) DO NOTHING;

-- Per-tenant opt-out flag
ALTER TABLE projects
  ADD COLUMN IF NOT EXISTS health_score_disabled BOOLEAN NOT NULL DEFAULT false;

INSERT INTO schema_migrations (filename, applied_at)
VALUES ('migrate_v2_3_0_health_score_config.sql', NOW())
ON CONFLICT (filename) DO NOTHING;
