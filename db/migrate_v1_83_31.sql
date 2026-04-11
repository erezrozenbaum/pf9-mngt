-- Migration: v1.83.31
-- Date: 2026-04-11
-- Description:
--   4.4  integration_routes — dedicated 'integration_key' Fernet secret
--        (no schema change; cipher storage is in the existing
--         external_integrations.auth_credential VARCHAR column)
--   4.3  vm_provisioning_routes — removed 15 per-request _ensure_tables()
--        calls; tables are now guaranteed at startup only
--        (no schema change)
--   4.2  performance_metrics — Redis-backed atomic counters with in-memory
--        fallback (no schema change)
--
-- No DDL changes are required.  This file serves as an audit trail for
-- operations teams and the run_migration.py idempotency check.

-- Idempotency marker (run_migration.py tracks applied migrations):
SELECT 'migrate_v1_83_31 recorded' AS status;
