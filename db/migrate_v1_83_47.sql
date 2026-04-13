-- v1.83.47 — WAN/QoS columns for migration_projects + LDAP dept-mapping table
-- New bandwidth / QoS columns on migration_projects
ALTER TABLE migration_projects
    ADD COLUMN IF NOT EXISTS wan_bandwidth_mbps      NUMERIC(10,2),
    ADD COLUMN IF NOT EXISTS throttle_mbps           NUMERIC(10,2),
    ADD COLUMN IF NOT EXISTS max_concurrent_migrations INTEGER;

-- New LDAP group → department mapping table
CREATE TABLE IF NOT EXISTS ldap_sync_dept_mappings (
    id                SERIAL PRIMARY KEY,
    config_id         INTEGER NOT NULL
                        REFERENCES ldap_sync_config(id) ON DELETE CASCADE,
    external_group_dn TEXT NOT NULL,
    department_name   VARCHAR(255) NOT NULL,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (config_id, external_group_dn)
);

CREATE INDEX IF NOT EXISTS idx_ldap_sync_dept_mappings_config
    ON ldap_sync_dept_mappings (config_id);
