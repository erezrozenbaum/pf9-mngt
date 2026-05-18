-- MIGRATION: Per-service PostgreSQL roles (v2.3.0)
-- Creates least-privilege roles for each service type.
-- Existing deployments using the shared 'pf9' superuser continue to work.
-- New deployments can configure per-service credentials via environment variables.
--
-- Usage after applying this migration:
--   Set a password for each role:
--     ALTER ROLE pf9_snapshot_svc LOGIN PASSWORD 'your_secret_here';
--   Then in docker-compose.yml override per-service:
--     SNAPSHOT_DB_USER=pf9_snapshot_svc
--     SNAPSHOT_DB_PASSWORD=your_secret_here

-- ---------------------------------------------------------------------------
-- Base role (no login — used only for privilege inheritance)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pf9_service_base') THEN
    CREATE ROLE pf9_service_base NOLOGIN;
  END IF;
END $$;

-- Grant CONNECT on the database to the base role
GRANT CONNECT ON DATABASE pf9_mgmt TO pf9_service_base;

-- ---------------------------------------------------------------------------
-- Snapshot Worker role
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pf9_snapshot_svc') THEN
    CREATE ROLE pf9_snapshot_svc NOLOGIN IN ROLE pf9_service_base;
  END IF;
END $$;

GRANT SELECT, INSERT, UPDATE ON
    snapshot_records, snapshot_runs, snapshot_policy_sets,
    snapshot_assignments, snapshot_exclusions,
    projects, servers, volumes
  TO pf9_snapshot_svc;

-- ---------------------------------------------------------------------------
-- Scheduler Worker role
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pf9_scheduler_svc') THEN
    CREATE ROLE pf9_scheduler_svc NOLOGIN IN ROLE pf9_service_base;
  END IF;
END $$;

GRANT SELECT ON
    projects, servers, volumes, drift_events, sla_commitments, support_tickets
  TO pf9_scheduler_svc;

GRANT SELECT, INSERT, UPDATE ON
    tenant_health_scores, metering_quotas, operational_insights, system_settings
  TO pf9_scheduler_svc;

-- ---------------------------------------------------------------------------
-- Notification Worker role
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pf9_notification_svc') THEN
    CREATE ROLE pf9_notification_svc NOLOGIN IN ROLE pf9_service_base;
  END IF;
END $$;

GRANT SELECT ON projects, tenant_health_scores, servers TO pf9_notification_svc;
GRANT SELECT, INSERT, UPDATE ON
    notification_log, notification_preferences,
    notification_channels, tenant_notification_prefs
  TO pf9_notification_svc;

-- ---------------------------------------------------------------------------
-- Metering Worker role
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pf9_metering_svc') THEN
    CREATE ROLE pf9_metering_svc NOLOGIN IN ROLE pf9_service_base;
  END IF;
END $$;

GRANT SELECT ON projects, servers, hypervisors, volumes TO pf9_metering_svc;
GRANT SELECT, INSERT, UPDATE ON
    metering_quotas, metering_resources, metering_config,
    metering_efficiency, metering_api_usage
  TO pf9_metering_svc;

-- ---------------------------------------------------------------------------
-- Intelligence Worker role
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pf9_intelligence_svc') THEN
    CREATE ROLE pf9_intelligence_svc NOLOGIN IN ROLE pf9_service_base;
  END IF;
END $$;

GRANT SELECT ON
    projects, servers, hypervisors, volumes, drift_events, support_tickets,
    tenant_health_scores, sla_commitments
  TO pf9_intelligence_svc;

GRANT SELECT, INSERT, UPDATE, DELETE ON operational_insights TO pf9_intelligence_svc;

-- ---------------------------------------------------------------------------
-- Backup Worker role
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pf9_backup_svc') THEN
    CREATE ROLE pf9_backup_svc NOLOGIN IN ROLE pf9_service_base;
  END IF;
END $$;

GRANT SELECT ON projects, servers TO pf9_backup_svc;
GRANT SELECT, INSERT, UPDATE ON backup_config, backup_history TO pf9_backup_svc;

-- ---------------------------------------------------------------------------
-- LDAP Sync Worker role
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pf9_ldap_svc') THEN
    CREATE ROLE pf9_ldap_svc NOLOGIN IN ROLE pf9_service_base;
  END IF;
END $$;

GRANT SELECT ON user_roles TO pf9_ldap_svc;
GRANT SELECT, INSERT, UPDATE, DELETE ON users TO pf9_ldap_svc;

-- Grant schema usage so roles can see tables
GRANT USAGE ON SCHEMA public TO pf9_service_base;

-- Record migration
INSERT INTO schema_migrations (filename, applied_at)
VALUES ('migrate_v2_3_0_db_roles.sql', NOW())
ON CONFLICT (filename) DO NOTHING;
