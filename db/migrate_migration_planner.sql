-- ============================================================
-- Migration Planner tables
-- VMware → Platform9 PCD migration intelligence & execution
-- ============================================================

-- ─────────────────────────────────────────────────────────────
-- 1. Migration Projects  (top-level container)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_projects (
    id              BIGSERIAL PRIMARY KEY,
    project_id      TEXT      NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
    name            TEXT      NOT NULL,
    description     TEXT,

    -- Lifecycle: draft → assessment → planned → approved → preparing → ready → executing → completed | cancelled → archived
    status          TEXT      NOT NULL DEFAULT 'draft',

    -- Topology: local | cross_site_dedicated | cross_site_internet
    topology_type   TEXT      NOT NULL DEFAULT 'local',

    -- Source-side settings
    source_nic_speed_gbps       NUMERIC(6,1) DEFAULT 10.0,
    source_usable_pct           NUMERIC(5,2) DEFAULT 40.0,

    -- Transport link (cross-site only)
    link_speed_gbps             NUMERIC(8,2),
    link_usable_pct             NUMERIC(5,2) DEFAULT 60.0,
    -- Internet-specific
    source_upload_mbps          NUMERIC(8,2),
    dest_download_mbps          NUMERIC(8,2),
    estimated_rtt_ms            NUMERIC(6,1),
    rtt_category                TEXT,           -- lt5 | 5-20 | 20-50 | 50-100 | gt100

    -- PCD / Agent-side settings
    target_ingress_speed_gbps   NUMERIC(6,1) DEFAULT 10.0,
    target_usable_pct           NUMERIC(5,2) DEFAULT 40.0,
    pcd_storage_write_mbps      NUMERIC(8,2) DEFAULT 500.0,

    -- Agent profile
    agent_count                 INTEGER DEFAULT 2,
    agent_concurrent_vms        INTEGER DEFAULT 5,
    agent_vcpu_per_slot         INTEGER DEFAULT 2,
    agent_ram_base_gb           NUMERIC(5,1) DEFAULT 2.0,
    agent_ram_per_slot_gb       NUMERIC(5,1) DEFAULT 1.0,
    agent_nic_speed_gbps        NUMERIC(6,1) DEFAULT 10.0,
    agent_nic_usable_pct        NUMERIC(5,2) DEFAULT 70.0,
    agent_disk_buffer_factor    NUMERIC(4,2) DEFAULT 1.2,

    -- Warm migration churn assumption
    daily_change_rate_pct       NUMERIC(5,2) DEFAULT 5.0,

    -- Schedule-aware planning
    migration_duration_days     INTEGER DEFAULT 30,
    working_hours_per_day       NUMERIC(4,1) DEFAULT 8.0,
    working_days_per_week       INTEGER DEFAULT 5,
    target_vms_per_day          INTEGER,

    -- Data retention / expiry
    auto_expire_days            INTEGER DEFAULT 90,

    -- RVTools upload metadata
    rvtools_filename            TEXT,
    rvtools_uploaded_at         TIMESTAMPTZ,
    rvtools_sheet_stats         JSONB DEFAULT '{}',  -- {"vInfo": 200, "vDisk": 450, ...}

    -- Audit
    created_by      TEXT      NOT NULL DEFAULT 'system',
    approved_by     TEXT,
    approved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mig_projects_status     ON migration_projects(status);
CREATE INDEX IF NOT EXISTS idx_mig_projects_created_at ON migration_projects(created_at DESC);

-- ─────────────────────────────────────────────────────────────
-- 2. Risk configuration (config-driven rules)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_risk_config (
    id              BIGSERIAL PRIMARY KEY,
    project_id      TEXT      NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    config_version  INTEGER   NOT NULL DEFAULT 1,
    rules           JSONB     NOT NULL DEFAULT '{
        "os_unsupported": ["Windows NT 4", "Windows 2000", "SCO", "Solaris", "AIX", "HP-UX", "FreeBSD"],
        "os_deprecated": ["Windows Server 2003", "Windows Server 2008", "Windows XP", "Windows Vista", "CentOS 6", "RHEL 5", "Ubuntu 12", "Ubuntu 14", "Debian 7", "Debian 8"],
        "os_warm_risky": ["Windows Server 2003", "Windows 2000", "Windows NT"],
        "os_cold_required": ["SCO", "Solaris", "AIX", "HP-UX", "FreeBSD"],
        "disk_large_threshold_gb": 2000,
        "disk_very_large_threshold_gb": 5000,
        "disk_count_high": 8,
        "snapshot_depth_warning": 3,
        "snapshot_depth_critical": 5,
        "snapshot_age_warning_days": 30,
        "multi_nic_threshold": 3,
        "high_ram_threshold_gb": 64,
        "high_disk_count_threshold": 6,
        "db_name_patterns": ["sql", "oracle", "mysql", "postgres", "mongo", "redis", "elastic", "kafka", "rabbit", "db-", "database"],
        "risk_weights": {
            "os_unsupported": 30,
            "os_deprecated": 15,
            "disk_very_large": 25,
            "disk_large": 10,
            "disk_count_high": 10,
            "snapshot_critical": 20,
            "snapshot_warning": 8,
            "snapshot_old": 5,
            "multi_nic": 10,
            "high_io_heuristic": 15,
            "cold_required_os": 20
        },
        "category_thresholds": {
            "green_max": 20,
            "yellow_max": 50
        }
    }',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mig_risk_config_project ON migration_risk_config(project_id);

-- ─────────────────────────────────────────────────────────────
-- 3. Tenant detection rules (config-driven)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_tenant_rules (
    id              BIGSERIAL PRIMARY KEY,
    project_id      TEXT      NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    -- Priority-ordered methods for tenant detection
    detection_config JSONB    NOT NULL DEFAULT '{
        "methods": [
            {"method": "vcd_folder", "enabled": true, "description": "Detect VMware Cloud Director Org/OrgVDC from folder and resource pool paths"},
            {"method": "folder_path", "enabled": true, "depth": 2, "description": "Use VM folder hierarchy (depth=2: /Datacenter/TenantName)"},
            {"method": "resource_pool", "enabled": true, "description": "Use resource pool name as tenant group"},
            {"method": "vapp_name", "enabled": true, "description": "Use vApp name as application group"},
            {"method": "vm_name_prefix", "enabled": true, "separator": "-", "prefix_parts": 1, "description": "Extract tenant from VM name prefix before separator"},
            {"method": "annotation_field", "enabled": false, "field_name": "Tenant", "description": "Use a custom annotation field for tenant"},
            {"method": "cluster", "enabled": true, "description": "Use cluster name as tenant (fallback for non-vCD)"}
        ],
        "fallback_tenant": "Unassigned",
        "orgvdc_detection": {
            "use_resource_pool": true,
            "use_folder_depth3": true
        }
    }',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mig_tenant_rules_project ON migration_tenant_rules(project_id);

-- ─────────────────────────────────────────────────────────────
-- 4. Detected / confirmed tenants
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_tenants (
    id              BIGSERIAL PRIMARY KEY,
    project_id      TEXT      NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    tenant_name     TEXT      NOT NULL,
    org_vdc         TEXT,
    detection_method TEXT,          -- folder_path | resource_pool | vapp_name | vm_name_prefix | annotation | manual
    confirmed       BOOLEAN   NOT NULL DEFAULT false,
    vm_count        INTEGER   DEFAULT 0,
    total_disk_gb   NUMERIC(12,2) DEFAULT 0,
    total_in_use_gb NUMERIC(12,2) DEFAULT 0,
    total_ram_mb    INTEGER   DEFAULT 0,
    total_vcpu      INTEGER   DEFAULT 0,
    -- Target mapping
    target_domain   TEXT,
    target_project  TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, tenant_name, org_vdc)
);

CREATE INDEX IF NOT EXISTS idx_mig_tenants_project ON migration_tenants(project_id);

-- ─────────────────────────────────────────────────────────────
-- 4b. Network infrastructure summary
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_networks (
    id              BIGSERIAL PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    network_name    TEXT NOT NULL,
    vlan_id         INT,
    network_type    TEXT DEFAULT 'standard',
    vm_count        INT DEFAULT 0,
    subnet          TEXT,
    gateway         TEXT,
    dns_servers     TEXT,
    ip_range        TEXT,
    pcd_target      TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, network_name)
);

CREATE INDEX IF NOT EXISTS idx_mig_networks_project ON migration_networks(project_id);

-- ─────────────────────────────────────────────────────────────
-- 5. Source ESXi hosts (from vHost sheet)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_hosts (
    id              BIGSERIAL PRIMARY KEY,
    project_id      TEXT      NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    host_name       TEXT      NOT NULL,
    cluster         TEXT,
    datacenter      TEXT,
    cpu_model       TEXT,
    cpu_count       INTEGER,
    cpu_cores       INTEGER,
    cpu_threads     INTEGER,
    ram_mb          INTEGER,
    nic_count       INTEGER,
    nic_speed_mbps  INTEGER,
    -- User overrides
    nic_speed_override_mbps INTEGER,
    usable_pct_override     NUMERIC(5,2),
    -- Computed effective bandwidth (filled by engine)
    effective_migration_mbps NUMERIC(10,2),
    vm_count        INTEGER   DEFAULT 0,
    esx_version     TEXT,
    raw_data        JSONB     DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, host_name)
);

CREATE INDEX IF NOT EXISTS idx_mig_hosts_project ON migration_hosts(project_id);

-- ─────────────────────────────────────────────────────────────
-- 6. Source clusters (from vCluster sheet)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_clusters (
    id              BIGSERIAL PRIMARY KEY,
    project_id      TEXT      NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    cluster_name    TEXT      NOT NULL,
    datacenter      TEXT,
    host_count      INTEGER,
    total_cpu_mhz   BIGINT,
    total_ram_mb    BIGINT,
    ha_enabled      BOOLEAN,
    drs_enabled     BOOLEAN,
    raw_data        JSONB     DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, cluster_name)
);

CREATE INDEX IF NOT EXISTS idx_mig_clusters_project ON migration_clusters(project_id);

-- ─────────────────────────────────────────────────────────────
-- 7. Source VMs (from vInfo sheet — main table)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_vms (
    id              BIGSERIAL PRIMARY KEY,
    project_id      TEXT      NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    vm_id           TEXT      NOT NULL DEFAULT gen_random_uuid()::text,

    -- Identity
    vm_name         TEXT      NOT NULL,
    power_state     TEXT,              -- poweredOn | poweredOff | suspended
    template        BOOLEAN   DEFAULT false,
    guest_os        TEXT,              -- OS according to config
    guest_os_tools  TEXT,              -- OS according to VMware Tools
    os_family       TEXT,              -- windows | linux | other (derived)

    -- Folder / org structure (raw from RVTools)
    folder_path     TEXT,
    resource_pool   TEXT,
    vapp_name       TEXT,
    annotation      TEXT,

    -- Tenant assignment (derived or manual)
    tenant_name     TEXT,
    org_vdc         TEXT,
    app_group       TEXT,              -- vApp or name-prefix group

    -- Compute
    cpu_count       INTEGER,
    ram_mb          INTEGER,
    -- Disk summary (detail in migration_vm_disks)
    total_disk_gb   NUMERIC(12,2),
    provisioned_mb  BIGINT DEFAULT 0,      -- from vInfo Provisioned MB
    in_use_mb       BIGINT DEFAULT 0,      -- from vInfo In Use MB
    in_use_gb       NUMERIC(12,2) DEFAULT 0, -- best-known used disk (vPartition or vInfo)
    partition_used_gb NUMERIC(12,2) DEFAULT 0, -- from vPartition sum
    disk_count      INTEGER DEFAULT 0,
    -- NIC summary (detail in migration_vm_nics)
    nic_count       INTEGER DEFAULT 0,
    network_name    TEXT,                  -- primary NIC network (aggregated)
    -- OS version (full string from RVTools)
    os_version      TEXT,
    -- Snapshot summary (detail in migration_snapshots)
    snapshot_count  INTEGER DEFAULT 0,
    snapshot_oldest_days INTEGER,

    -- Host / cluster placement
    host_name       TEXT,
    cluster         TEXT,
    datacenter      TEXT,

    -- RVTools extra fields
    vm_uuid         TEXT,
    firmware        TEXT,              -- bios | efi
    boot_required   TEXT,
    change_tracking BOOLEAN,           -- CBT enabled?
    connection_state TEXT,             -- connected | disconnected
    dns_name        TEXT,
    primary_ip      TEXT,

    -- Risk scoring (filled by engine)
    risk_score      NUMERIC(5,1),
    risk_category   TEXT,              -- GREEN | YELLOW | RED
    risk_reasons    JSONB     DEFAULT '[]',

    -- Migration mode (filled by engine)
    migration_mode  TEXT,              -- warm_eligible | warm_risky | cold_required
    mode_reasons    JSONB     DEFAULT '[]',

    -- Estimation (filled by engine — Phase 3)
    phase1_duration_hours   NUMERIC(8,2),
    cutover_downtime_hours  NUMERIC(8,2),
    total_migration_hours   NUMERIC(8,2),
    production_impact       TEXT,       -- LOW | MEDIUM | HIGH

    -- Target mapping (filled by readiness check — Phase 4)
    target_flavor   TEXT,
    target_flavor_id TEXT,
    target_network  TEXT,
    target_project  TEXT,

    -- Manual overrides
    exclude_from_migration BOOLEAN DEFAULT false,
    exclude_reason  TEXT,
    manual_mode_override TEXT,         -- warm | cold | null (use computed)
    priority        INTEGER DEFAULT 50,  -- 1=highest, 100=lowest

    raw_data        JSONB     DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, vm_name)
);

CREATE INDEX IF NOT EXISTS idx_mig_vms_project      ON migration_vms(project_id);
CREATE INDEX IF NOT EXISTS idx_mig_vms_tenant        ON migration_vms(project_id, tenant_name);
CREATE INDEX IF NOT EXISTS idx_mig_vms_host          ON migration_vms(project_id, host_name);
CREATE INDEX IF NOT EXISTS idx_mig_vms_risk          ON migration_vms(project_id, risk_category);
CREATE INDEX IF NOT EXISTS idx_mig_vms_mode          ON migration_vms(project_id, migration_mode);
CREATE INDEX IF NOT EXISTS idx_mig_vms_cluster       ON migration_vms(project_id, cluster);

-- ─────────────────────────────────────────────────────────────
-- 8. VM Disks (from vDisk sheet)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_vm_disks (
    id              BIGSERIAL PRIMARY KEY,
    project_id      TEXT      NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    vm_name         TEXT      NOT NULL,
    disk_label      TEXT,
    disk_path       TEXT,
    capacity_gb     NUMERIC(12,2),
    consumed_gb     NUMERIC(12,2),         -- actual used space (from vPartition join)
    thin_provisioned BOOLEAN,
    eagerly_scrub   BOOLEAN,
    datastore       TEXT,
    raw_data        JSONB     DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mig_vm_disks_project ON migration_vm_disks(project_id);
CREATE INDEX IF NOT EXISTS idx_mig_vm_disks_vm      ON migration_vm_disks(project_id, vm_name);

-- ─────────────────────────────────────────────────────────────
-- 9. VM NICs (from vNIC sheet)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_vm_nics (
    id              BIGSERIAL PRIMARY KEY,
    project_id      TEXT      NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    vm_name         TEXT      NOT NULL,
    nic_label       TEXT,
    adapter_type    TEXT,              -- vmxnet3 | e1000 | e1000e | ...
    network_name    TEXT,
    connected       BOOLEAN,
    mac_address     TEXT,
    ip_address      TEXT,
    -- Target mapping
    target_network  TEXT,
    raw_data        JSONB     DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mig_vm_nics_project ON migration_vm_nics(project_id);
CREATE INDEX IF NOT EXISTS idx_mig_vm_nics_vm      ON migration_vm_nics(project_id, vm_name);

-- ─────────────────────────────────────────────────────────────
-- 10. Snapshots (from vSnapshot sheet)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_vm_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    project_id      TEXT      NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    vm_name         TEXT      NOT NULL,
    snapshot_name   TEXT,
    description     TEXT,
    created_date    TIMESTAMPTZ,
    size_gb         NUMERIC(12,2),
    is_current      BOOLEAN DEFAULT false,
    raw_data        JSONB     DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mig_vm_snapshots_project ON migration_vm_snapshots(project_id);
CREATE INDEX IF NOT EXISTS idx_mig_vm_snapshots_vm      ON migration_vm_snapshots(project_id, vm_name);

-- ─────────────────────────────────────────────────────────────
-- 11. Migration waves (Phase 6 — schema defined now for FK refs)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_waves (
    id              BIGSERIAL PRIMARY KEY,
    project_id      TEXT      NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    wave_number     INTEGER   NOT NULL,
    name            TEXT,
    description     TEXT,
    status          TEXT      NOT NULL DEFAULT 'planned',  -- planned | approved | executing | completed | cancelled
    vm_count        INTEGER   DEFAULT 0,
    total_disk_gb   NUMERIC(12,2) DEFAULT 0,
    estimated_phase1_hours NUMERIC(8,2),
    estimated_cutover_hours NUMERIC(8,2),
    maintenance_window_start TIMESTAMPTZ,
    maintenance_window_end   TIMESTAMPTZ,
    bottleneck_info JSONB     DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, wave_number)
);

CREATE INDEX IF NOT EXISTS idx_mig_waves_project ON migration_waves(project_id);

-- ─────────────────────────────────────────────────────────────
-- 12. Wave VM assignments
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_wave_vms (
    id              BIGSERIAL PRIMARY KEY,
    project_id      TEXT      NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    wave_number     INTEGER   NOT NULL,
    vm_name         TEXT      NOT NULL,
    agent_assignment TEXT,
    migration_order INTEGER,
    estimated_start TIMESTAMPTZ,
    estimated_end   TIMESTAMPTZ,
    status          TEXT      NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, vm_name)
);

CREATE INDEX IF NOT EXISTS idx_mig_wave_vms_project ON migration_wave_vms(project_id);
CREATE INDEX IF NOT EXISTS idx_mig_wave_vms_wave    ON migration_wave_vms(project_id, wave_number);

-- ─────────────────────────────────────────────────────────────
-- 13. Target readiness gaps (Phase 4)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_target_gaps (
    id              BIGSERIAL PRIMARY KEY,
    project_id      TEXT      NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    gap_type        TEXT      NOT NULL,  -- missing_domain | missing_project | missing_flavor | missing_network | missing_router | missing_fip_pool | missing_secgroup | quota_shortfall
    category        TEXT,                -- tenant | compute | network | storage
    entity_name     TEXT      NOT NULL,  -- name of missing/mismatched resource
    tenant_name     TEXT,
    detail          JSONB     DEFAULT '{}',
    severity        TEXT      NOT NULL DEFAULT 'warning',  -- info | warning | critical
    resolved        BOOLEAN   DEFAULT false,
    resolved_by     TEXT,
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mig_target_gaps_project ON migration_target_gaps(project_id);
CREATE INDEX IF NOT EXISTS idx_mig_target_gaps_type    ON migration_target_gaps(project_id, gap_type);

-- ─────────────────────────────────────────────────────────────
-- 14. Preparation tasks (Phase 5 — preview/execute)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_prep_tasks (
    id              BIGSERIAL PRIMARY KEY,
    project_id      TEXT      NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    task_order      INTEGER   NOT NULL,
    task_type       TEXT      NOT NULL,  -- create_domain | create_project | set_quotas | create_network | create_router | create_fip_pool | create_secgroup | create_user | assign_role
    task_name       TEXT      NOT NULL,
    tenant_name     TEXT,
    detail          JSONB     DEFAULT '{}',     -- parameters for creation
    status          TEXT      NOT NULL DEFAULT 'pending',  -- pending | approved | running | completed | failed | skipped
    resource_id     TEXT,                        -- created OpenStack resource ID
    result          JSONB     DEFAULT '{}',
    error_message   TEXT,
    executed_by     TEXT,
    executed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mig_prep_tasks_project ON migration_prep_tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_mig_prep_tasks_status  ON migration_prep_tasks(project_id, status);

-- ─────────────────────────────────────────────────────────────
-- 15. Project archives (lightweight summary after purge)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_project_archives (
    id              BIGSERIAL PRIMARY KEY,
    original_project_id TEXT NOT NULL,
    name            TEXT      NOT NULL,
    summary         JSONB     NOT NULL DEFAULT '{}',  -- vm_count, disk_tb, tenant_count, risk_summary, outcome
    archived_by     TEXT,
    archived_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ═══════════════════════════════════════════════════════════════
-- RBAC permissions for migration resource
-- ═══════════════════════════════════════════════════════════════
INSERT INTO role_permissions (role, resource, action) VALUES
    ('viewer',     'migration', 'read'),
    ('operator',   'migration', 'read'),
    ('technical',  'migration', 'read'),
    ('technical',  'migration', 'write'),
    ('admin',      'migration', 'read'),
    ('admin',      'migration', 'write'),
    ('admin',      'migration', 'admin'),
    ('superadmin', 'migration', 'read'),
    ('superadmin', 'migration', 'write'),
    ('superadmin', 'migration', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;

-- ═══════════════════════════════════════════════════════════════
-- Navigation: Migration Planning group + nav item
-- ═══════════════════════════════════════════════════════════════
INSERT INTO nav_groups (key, label, icon, description, sort_order) VALUES
    ('migration_planning', 'Migration Planning', '🚀', 'VMware to PCD migration intelligence and execution', 8)
ON CONFLICT (key) DO NOTHING;

INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order, is_action) VALUES
    ((SELECT id FROM nav_groups WHERE key='migration_planning'), 'migration_planner', 'Migration Planner', '🚀', '/migration_planner', 'migration', 1, true)
ON CONFLICT (key) DO NOTHING;

-- Department visibility: Engineering, Tier3 Support, Management, Marketing
INSERT INTO department_nav_groups (department_id, nav_group_id)
SELECT d.id, ng.id
FROM departments d, nav_groups ng
WHERE ng.key = 'migration_planning'
  AND d.name IN ('Engineering', 'Tier3 Support', 'Management', 'Marketing')
ON CONFLICT (department_id, nav_group_id) DO NOTHING;

INSERT INTO department_nav_items (department_id, nav_item_id)
SELECT d.id, ni.id
FROM departments d, nav_items ni
WHERE ni.key = 'migration_planner'
  AND d.name IN ('Engineering', 'Tier3 Support', 'Management', 'Marketing')
ON CONFLICT (department_id, nav_item_id) DO NOTHING;
