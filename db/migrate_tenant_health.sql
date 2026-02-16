-- ============================================================
-- Migration: Tenant Health View  (v1.10.0)
-- Creates materialised views that aggregate per-project health
-- metrics from existing resource tables.
-- Idempotent — safe to re-run.
-- ============================================================

-- 1. Per-tenant resource counts & status breakdown
DROP VIEW IF EXISTS v_tenant_health CASCADE;
CREATE OR REPLACE VIEW v_tenant_health AS
WITH server_stats AS (
    SELECT
        s.project_id,
        COUNT(*)                                             AS total_servers,
        COUNT(*) FILTER (WHERE s.status = 'ACTIVE')          AS active_servers,
        COUNT(*) FILTER (WHERE s.status = 'SHUTOFF')         AS shutoff_servers,
        COUNT(*) FILTER (WHERE s.status = 'ERROR')           AS error_servers,
        COUNT(*) FILTER (WHERE s.status NOT IN ('ACTIVE','SHUTOFF','ERROR')) AS other_servers,
        -- Compute resource allocation from flavors
        COALESCE(SUM(f.vcpus),  0)                           AS total_vcpus,
        COALESCE(SUM(f.ram_mb), 0)                           AS total_ram_mb,
        COALESCE(SUM(f.disk_gb),0)                           AS total_flavor_disk_gb,
        -- Active-only allocation
        COALESCE(SUM(f.vcpus)  FILTER (WHERE s.status = 'ACTIVE'), 0) AS active_vcpus,
        COALESCE(SUM(f.ram_mb) FILTER (WHERE s.status = 'ACTIVE'), 0) AS active_ram_mb,
        -- Count by hypervisor (for heatmap)
        COUNT(DISTINCT s.hypervisor_hostname)                AS hypervisor_count,
        -- Power state ratio
        ROUND(
            100.0 * COUNT(*) FILTER (WHERE s.status = 'ACTIVE')
            / NULLIF(COUNT(*), 0), 1
        )                                                    AS power_on_pct
    FROM servers s
    LEFT JOIN flavors f ON s.flavor_id = f.id
    GROUP BY s.project_id
),
volume_stats AS (
    SELECT
        project_id,
        COUNT(*)                                             AS total_volumes,
        COALESCE(SUM(size_gb), 0)                            AS total_volume_gb,
        COUNT(*) FILTER (WHERE status = 'available')         AS available_volumes,
        COUNT(*) FILTER (WHERE status = 'in-use')            AS in_use_volumes,
        COUNT(*) FILTER (WHERE status = 'error')             AS error_volumes,
        COUNT(*) FILTER (WHERE status NOT IN ('available','in-use','error')) AS other_volumes
    FROM volumes GROUP BY project_id
),
network_stats AS (
    SELECT project_id, COUNT(*) AS total_networks
    FROM networks GROUP BY project_id
),
subnet_stats AS (
    SELECT n.project_id, COUNT(*) AS total_subnets
    FROM subnets s JOIN networks n ON s.network_id = n.id
    GROUP BY n.project_id
),
port_stats AS (
    SELECT project_id, COUNT(*) AS total_ports
    FROM ports GROUP BY project_id
),
fip_stats AS (
    SELECT
        project_id,
        COUNT(*)                                             AS total_floating_ips,
        COUNT(*) FILTER (WHERE status = 'ACTIVE')           AS active_fips,
        COUNT(*) FILTER (WHERE status = 'DOWN')             AS down_fips
    FROM floating_ips GROUP BY project_id
),
sg_stats AS (
    SELECT project_id, COUNT(*) AS total_security_groups
    FROM security_groups GROUP BY project_id
),
snap_stats AS (
    SELECT
        project_id,
        COUNT(*)                                             AS total_snapshots,
        COUNT(*) FILTER (WHERE status = 'available')         AS available_snapshots,
        COUNT(*) FILTER (WHERE status = 'error')             AS error_snapshots,
        COALESCE(SUM(size_gb), 0)                            AS total_snapshot_gb
    FROM snapshots GROUP BY project_id
),
drift_stats AS (
    SELECT
        project_id,
        COUNT(*)                                                                          AS total_drift_events,
        COUNT(*) FILTER (WHERE severity = 'critical')                                     AS critical_drift,
        COUNT(*) FILTER (WHERE severity = 'warning')                                      AS warning_drift,
        COUNT(*) FILTER (WHERE severity = 'info')                                         AS info_drift,
        COUNT(*) FILTER (WHERE acknowledged = FALSE)                               AS new_drift,
        COUNT(*) FILTER (WHERE detected_at >= NOW() - INTERVAL '7 days')                  AS drift_7d,
        COUNT(*) FILTER (WHERE detected_at >= NOW() - INTERVAL '30 days')                 AS drift_30d
    FROM drift_events GROUP BY project_id
),
compliance_stats AS (
    SELECT
        project_id,
        COUNT(*)                                             AS total_compliance_items,
        COUNT(*) FILTER (WHERE is_compliant = TRUE)          AS compliant_items,
        ROUND(
            100.0 * COUNT(*) FILTER (WHERE is_compliant = TRUE)
            / NULLIF(COUNT(*), 0), 1
        )                                                    AS compliance_pct
    FROM compliance_details GROUP BY project_id
)
SELECT
    p.id                          AS project_id,
    p.name                        AS project_name,
    d.id                          AS domain_id,
    d.name                        AS domain_name,
    -- Servers
    COALESCE(ss.total_servers, 0)     AS total_servers,
    COALESCE(ss.active_servers, 0)    AS active_servers,
    COALESCE(ss.shutoff_servers, 0)   AS shutoff_servers,
    COALESCE(ss.error_servers, 0)     AS error_servers,
    COALESCE(ss.other_servers, 0)     AS other_servers,
    -- vCPU / RAM allocation
    COALESCE(ss.total_vcpus, 0)       AS total_vcpus,
    COALESCE(ss.total_ram_mb, 0)      AS total_ram_mb,
    COALESCE(ss.total_flavor_disk_gb, 0) AS total_flavor_disk_gb,
    COALESCE(ss.active_vcpus, 0)      AS active_vcpus,
    COALESCE(ss.active_ram_mb, 0)     AS active_ram_mb,
    COALESCE(ss.hypervisor_count, 0)  AS hypervisor_count,
    COALESCE(ss.power_on_pct, 0)      AS power_on_pct,
    -- Volumes
    COALESCE(vs.total_volumes, 0)     AS total_volumes,
    COALESCE(vs.total_volume_gb, 0)   AS total_volume_gb,
    COALESCE(vs.available_volumes, 0) AS available_volumes,
    COALESCE(vs.in_use_volumes, 0)    AS in_use_volumes,
    COALESCE(vs.error_volumes, 0)     AS error_volumes,
    COALESCE(vs.other_volumes, 0)     AS other_volumes,
    -- Networking
    COALESCE(ns.total_networks, 0)        AS total_networks,
    COALESCE(sn.total_subnets, 0)         AS total_subnets,
    COALESCE(ps.total_ports, 0)           AS total_ports,
    COALESCE(fs.total_floating_ips, 0)    AS total_floating_ips,
    COALESCE(fs.active_fips, 0)           AS active_fips,
    COALESCE(fs.down_fips, 0)             AS down_fips,
    -- Security
    COALESCE(sgs.total_security_groups, 0) AS total_security_groups,
    -- Snapshots
    COALESCE(snp.total_snapshots, 0)       AS total_snapshots,
    COALESCE(snp.available_snapshots, 0)   AS available_snapshots,
    COALESCE(snp.error_snapshots, 0)       AS error_snapshots,
    COALESCE(snp.total_snapshot_gb, 0)     AS total_snapshot_gb,
    -- Drift
    COALESCE(dr.total_drift_events, 0) AS total_drift_events,
    COALESCE(dr.critical_drift, 0)     AS critical_drift,
    COALESCE(dr.warning_drift, 0)      AS warning_drift,
    COALESCE(dr.info_drift, 0)         AS info_drift,
    COALESCE(dr.new_drift, 0)          AS new_drift,
    COALESCE(dr.drift_7d, 0)           AS drift_7d,
    COALESCE(dr.drift_30d, 0)          AS drift_30d,
    -- Compliance
    COALESCE(cs.total_compliance_items, 0)  AS total_compliance_items,
    COALESCE(cs.compliant_items, 0)         AS compliant_items,
    COALESCE(cs.compliance_pct, 0)          AS compliance_pct,
    -- Health score (0-100): deductions for problems
    GREATEST(0, LEAST(100,
        100
        -- Deduct for error VMs  (up to -20)
        - LEAST(20, COALESCE(ss.error_servers, 0) * 10)
        -- Deduct for shutoff VMs  (up to -10)
        - LEAST(10, COALESCE(ss.shutoff_servers, 0) * 2)
        -- Deduct for error volumes  (up to -15)
        - LEAST(15, COALESCE(vs.error_volumes, 0) * 5)
        -- Deduct for error snapshots  (up to -10)
        - LEAST(10, COALESCE(snp.error_snapshots, 0) * 5)
        -- Deduct for low compliance  (up to -20)
        - CASE
            WHEN COALESCE(cs.total_compliance_items, 0) = 0 THEN 0
            ELSE LEAST(20, GREATEST(0, (100 - COALESCE(cs.compliance_pct, 100)) * 0.2))
          END
        -- Deduct for critical drift  (up to -15)
        - LEAST(15, COALESCE(dr.critical_drift, 0) * 5)
        -- Deduct for warning drift  (up to -10)
        - LEAST(10, COALESCE(dr.warning_drift, 0) * 2)
    ))::INT                                  AS health_score
FROM projects p
JOIN domains d ON p.domain_id = d.id
LEFT JOIN server_stats     ss  ON ss.project_id = p.id
LEFT JOIN volume_stats     vs  ON vs.project_id = p.id
LEFT JOIN network_stats    ns  ON ns.project_id = p.id
LEFT JOIN subnet_stats     sn  ON sn.project_id = p.id
LEFT JOIN port_stats       ps  ON ps.project_id = p.id
LEFT JOIN fip_stats        fs  ON fs.project_id = p.id
LEFT JOIN sg_stats         sgs ON sgs.project_id = p.id
LEFT JOIN snap_stats       snp ON snp.project_id = p.id
LEFT JOIN drift_stats      dr  ON dr.project_id = p.id
LEFT JOIN compliance_stats cs  ON cs.project_id = p.id;

-- 2. RBAC permissions for tenant_health
INSERT INTO role_permissions (role, resource, action)
VALUES
    ('viewer',     'tenant_health', 'read'),
    ('operator',   'tenant_health', 'read'),
    ('admin',      'tenant_health', 'read'),
    ('admin',      'tenant_health', 'admin'),
    ('superadmin', 'tenant_health', 'read'),
    ('superadmin', 'tenant_health', 'admin')
ON CONFLICT DO NOTHING;
