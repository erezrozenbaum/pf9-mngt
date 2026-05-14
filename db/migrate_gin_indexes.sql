-- Migration: GIN indexes on raw_json JSONB columns + expression indexes
-- =====================================================================
-- Addresses full sequential scans on raw_json JSONB columns in the three
-- highest-query tables: servers, hypervisors, volumes.
--
-- Uses CREATE INDEX CONCURRENTLY so this can be run on a live database
-- without locking the tables.  Run outside a transaction block:
--
--   psql -U pf9 -d pf9_mgmt -f migrate_gin_indexes.sql
--
-- NOTE: CONCURRENTLY cannot run inside a transaction — this file must be
-- executed directly via psql, not wrapped in BEGIN/COMMIT.
-- =====================================================================

-- 1. Full GIN indexes on raw_json (JSONB containment queries: @>, ?)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_servers_raw_json
    ON servers USING GIN (raw_json);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_hypervisors_raw_json
    ON hypervisors USING GIN (raw_json);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_volumes_raw_json
    ON volumes USING GIN (raw_json);

-- 2. Expression indexes for the most-queried scalar subfields
--    (faster than GIN for equality filters on a single known key)

-- servers.raw_json->>'status'  (used in every VM dashboard query)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_servers_raw_status
    ON servers ((raw_json->>'status'));

-- servers.raw_json->>'power_state'  (powered-on/off filters)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_servers_raw_power_state
    ON servers ((raw_json->>'power_state'));

-- hypervisors.raw_json->>'vcpus_used'  (capacity dashboard)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_hypervisors_raw_vcpus_used
    ON hypervisors ((raw_json->>'vcpus_used'));

-- hypervisors.raw_json->>'memory_mb_used'  (RAM capacity)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_hypervisors_raw_memory_used
    ON hypervisors ((raw_json->>'memory_mb_used'));

-- volumes.raw_json->>'status'  (volume status filter)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_volumes_raw_status
    ON volumes ((raw_json->>'status'));

-- 3. Verify
SELECT tablename, indexname
FROM   pg_indexes
WHERE  tablename IN ('servers', 'hypervisors', 'volumes')
  AND  (indexname LIKE '%raw%' OR indexname LIKE '%gin%')
ORDER  BY tablename, indexname;
