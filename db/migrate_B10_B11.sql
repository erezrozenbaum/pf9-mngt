-- =====================================================================
-- MIGRATION: Batch 10 + 11
-- Batch 10: Worker Observability & Resilience
-- Batch 11: Frontend Resilience & Polish (backend-side schema changes)
-- Safe to run multiple times — all statements use IF NOT EXISTS / ADD COLUMN IF NOT EXISTS.
-- =====================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- B10.4: conflict_strategy for LDAP sync configs
-- Controls how attribute conflicts are resolved between external LDAP and
-- locally-overridden user records.
--   ldap_wins (default): external directory always wins (existing behaviour)
--   local_wins:          skip updating attributes that have been locally overridden
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE ldap_sync_config
    ADD COLUMN IF NOT EXISTS conflict_strategy VARCHAR(20) NOT NULL DEFAULT 'ldap_wins'
    CHECK (conflict_strategy IN ('ldap_wins', 'local_wins'));

COMMENT ON COLUMN ldap_sync_config.conflict_strategy IS
    'ldap_wins: external LDAP attributes always overwrite local values (default). '
    'local_wins: attributes of locally-overridden users are preserved.';
