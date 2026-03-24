-- Migration: Fix v_most_changed_resources to not reference non-existent 'recorded_at' column.
-- v_recent_changes uses created_at/modified_at/deleted_at; COALESCE provides the equivalent.
CREATE OR REPLACE VIEW v_most_changed_resources AS
SELECT
    resource_type,
    resource_id,
    resource_name,
    project_id,
    project_name,
    domain_id,
    domain_name,
    status,
    created_at,
    modified_at,
    deleted_at,
    change_type,
    COALESCE(modified_at, created_at, deleted_at) AS recorded_at,
    COUNT(*) OVER (PARTITION BY resource_type, resource_id) AS change_count,
    COALESCE(modified_at, created_at, deleted_at) AS last_change
FROM v_recent_changes
ORDER BY COALESCE(modified_at, created_at, deleted_at) DESC;
