-- Migration: Add recorded_at column to v_recent_changes.
-- Multiple queries in main.py filter/sort by recorded_at against v_recent_changes,
-- but the original view had no such column (only created_at, modified_at, deleted_at).
-- Fix: wrap the UNION ALL in a subquery and expose COALESCE(modified_at, created_at, deleted_at)
-- as recorded_at so all callers get a stable timestamp regardless of resource type.
--
-- Also recreates v_most_changed_resources to use the new recorded_at directly
-- (dropping the redundant intermediate COALESCE).

-- Drop dependent view first so CREATE OR REPLACE succeeds on v_recent_changes.
DROP VIEW IF EXISTS v_most_changed_resources;

CREATE OR REPLACE VIEW v_recent_changes AS
SELECT
    resource_type, resource_id, resource_name,
    project_id, project_name, domain_id, domain_name,
    status, created_at, modified_at, deleted_at, change_type,
    COALESCE(modified_at, created_at, deleted_at) AS recorded_at
FROM (
    SELECT
        'server' AS resource_type,
        s.id AS resource_id,
        s.name AS resource_name,
        s.project_id,
        p.name AS project_name,
        d.id AS domain_id,
        d.name AS domain_name,
        s.status,
        s.created_at,
        s.last_seen_at AS modified_at,
        NULL::TIMESTAMPTZ AS deleted_at,
        'active' AS change_type
    FROM servers s
    LEFT JOIN projects p ON s.project_id = p.id
    LEFT JOIN domains d ON p.domain_id = d.id
    UNION ALL
    SELECT
        'volume',
        v.id,
        v.name,
        v.project_id,
        p.name,
        d.id,
        d.name,
        v.status,
        v.created_at,
        v.last_seen_at,
        NULL,
        'active'
    FROM volumes v
    LEFT JOIN projects p ON v.project_id = p.id
    LEFT JOIN domains d ON p.domain_id = d.id
    UNION ALL
    SELECT
        'snapshot',
        s.id,
        s.name,
        s.project_id,
        p.name,
        d.id,
        d.name,
        s.status,
        s.created_at,
        s.last_seen_at,
        NULL,
        'active'
    FROM snapshots s
    LEFT JOIN projects p ON s.project_id = p.id
    LEFT JOIN domains d ON p.domain_id = d.id
    UNION ALL
    SELECT
        dh.resource_type,
        dh.resource_id,
        dh.resource_name,
        NULL AS project_id,
        dh.project_name,
        NULL AS domain_id,
        dh.domain_name,
        NULL AS status,
        NULL AS created_at,
        NULL AS modified_at,
        dh.deleted_at,
        'deleted'
    FROM deletions_history dh
) _base;

CREATE OR REPLACE VIEW v_most_changed_resources AS
SELECT
    resource_type, resource_id, resource_name,
    project_id, project_name, domain_id, domain_name,
    status, created_at, modified_at, deleted_at, change_type,
    recorded_at,
    COUNT(*) OVER (PARTITION BY resource_type, resource_id) AS change_count,
    recorded_at AS last_change
FROM v_recent_changes
ORDER BY recorded_at DESC;
