CREATE VIEW v_comprehensive_changes AS
-- Servers
SELECT 'server'::text AS resource_type,
    sh.server_id AS resource_id,
    COALESCE((sh.raw_json ->> 'name'::text), ('Server-'::text || left(sh.server_id, 8))) AS resource_name,
    sh.change_hash,
    sh.last_seen_at AS recorded_at,
    (sh.raw_json ->> 'project_name'::text) AS project_name,
    (sh.raw_json ->> 'domain_name'::text) AS domain_name,
    COALESCE(((sh.raw_json ->> 'created'::text))::timestamp without time zone, ((sh.raw_json ->> 'created_at'::text))::timestamp without time zone) AS actual_time,
    'Server lifecycle change'::text AS change_description
FROM servers_history sh

UNION ALL

-- Users (NEW)
SELECT 'user'::text AS resource_type,
    uh.user_id AS resource_id,
    uh.name AS resource_name,
    uh.change_hash,
    uh.recorded_at,
    NULL::text AS project_name,
    (SELECT d.name FROM domains d WHERE d.id = uh.domain_id) AS domain_name,
    uh.created_at AS actual_time,
    'User account change'::text AS change_description
FROM users_history uh

UNION ALL

-- Roles (NEW) 
SELECT 'role'::text AS resource_type,
    rh.role_id AS resource_id,
    rh.name AS resource_name,
    rh.change_hash,
    rh.recorded_at,
    NULL::text AS project_name,
    NULL::text AS domain_name,
    COALESCE(((rh.raw_json ->> 'created_at'::text))::timestamp with time zone) AS actual_time,
    'Role definition change'::text AS change_description
FROM roles_history rh

UNION ALL

-- Volumes
SELECT 'volume'::text AS resource_type,
    vh.volume_id AS resource_id,
    COALESCE(NULLIF((vh.raw_json ->> 'name'::text), ''::text), (vh.raw_json ->> 'display_name'::text), ('Volume-'::text || left(vh.volume_id, 8))) AS resource_name,
    vh.change_hash,
    vh.last_seen_at AS recorded_at,
    (vh.raw_json ->> 'project_name'::text) AS project_name,
    (vh.raw_json ->> 'domain_name'::text) AS domain_name,
    COALESCE(((vh.raw_json ->> 'created_at'::text))::timestamp without time zone, ((vh.raw_json ->> 'updated_at'::text))::timestamp without time zone) AS actual_time,
    'Volume lifecycle change'::text AS change_description
FROM volumes_history vh

UNION ALL

-- Ports
SELECT 'port'::text AS resource_type,
    ph.port_id AS resource_id,
    COALESCE((ph.raw_json ->> 'name'::text), (ph.raw_json ->> 'fixed_ips'::text), ('Port-'::text || left(ph.port_id, 8))) AS resource_name,
    ph.change_hash,
    ph.recorded_at,
    (ph.raw_json ->> 'project_name'::text) AS project_name,
    (ph.raw_json ->> 'domain_name'::text) AS domain_name,
    COALESCE(((ph.raw_json ->> 'created_at'::text))::timestamp without time zone) AS actual_time,
    'Network port change'::text AS change_description
FROM ports_history ph

UNION ALL

-- Floating IPs
SELECT 'floating_ip'::text AS resource_type,
    fh.floating_ip_id AS resource_id,
    COALESCE(fh.floating_ip, (fh.raw_json ->> 'floating_ip_address'::text), ('IP-'::text || left(fh.floating_ip_id, 8))) AS resource_name,
    fh.change_hash,
    fh.recorded_at,
    (fh.raw_json ->> 'project_name'::text) AS project_name,
    (fh.raw_json ->> 'domain_name'::text) AS domain_name,
    COALESCE(((fh.raw_json ->> 'created_at'::text))::timestamp without time zone) AS actual_time,
    'Floating IP change'::text AS change_description
FROM floating_ips_history fh

UNION ALL

-- Networks
SELECT 'network'::text AS resource_type,
    nh.network_id AS resource_id,
    nh.name AS resource_name,
    nh.change_hash,
    nh.recorded_at,
    (nh.raw_json ->> 'project_name'::text) AS project_name,
    (nh.raw_json ->> 'domain_name'::text) AS domain_name,
    COALESCE(((nh.raw_json ->> 'created_at'::text))::timestamp without time zone) AS actual_time,
    'Network configuration change'::text AS change_description
FROM networks_history nh

UNION ALL

-- Deletions
SELECT deletions_history.resource_type,
    deletions_history.resource_id,
    (deletions_history.resource_name || ' (DELETED)'::text) AS resource_name,
    ('DELETION-'::text || deletions_history.resource_id) AS change_hash,
    deletions_history.deleted_at AS recorded_at,
    deletions_history.project_name,
    deletions_history.domain_name,
    deletions_history.last_seen_before_deletion AS actual_time,
    'Resource deletion detected'::text AS change_description
FROM deletions_history

UNION ALL

-- Domains
SELECT 'domain'::text AS resource_type,
    dh.domain_id AS resource_id,
    dh.name AS resource_name,
    dh.change_hash,
    dh.recorded_at,
    NULL::text AS project_name,
    NULL::text AS domain_name,
    COALESCE(((dh.raw_json ->> 'created_at'::text))::timestamp with time zone, ((dh.raw_json ->> 'updated_at'::text))::timestamp with time zone, ((dh.raw_json ->> 'created'::text))::timestamp with time zone, (SELECT min(domains_history.recorded_at) FROM domains_history WHERE domains_history.domain_id = dh.domain_id)) AS actual_time,
    'Infrastructure component change'::text AS change_description
FROM domains_history dh

UNION ALL

-- Projects
SELECT 'project'::text AS resource_type,
    ph.project_id AS resource_id,
    ph.name AS resource_name,
    ph.change_hash,
    ph.recorded_at,
    NULL::text AS project_name,
    NULL::text AS domain_name,
    COALESCE(((ph.raw_json ->> 'created_at'::text))::timestamp with time zone, ((ph.raw_json ->> 'updated_at'::text))::timestamp with time zone, ((ph.raw_json ->> 'created'::text))::timestamp with time zone, (SELECT min(projects_history.recorded_at) FROM projects_history WHERE projects_history.project_id = ph.project_id)) AS actual_time,
    'Infrastructure component change'::text AS change_description
FROM projects_history ph

UNION ALL

-- Flavors
SELECT 'flavor'::text AS resource_type,
    fh.flavor_id AS resource_id,
    fh.name AS resource_name,
    fh.change_hash,
    fh.recorded_at,
    NULL::text AS project_name,
    NULL::text AS domain_name,
    COALESCE(((fh.raw_json ->> 'created_at'::text))::timestamp with time zone, ((fh.raw_json ->> 'updated_at'::text))::timestamp with time zone, ((fh.raw_json ->> 'created'::text))::timestamp with time zone, (SELECT min(flavors_history.recorded_at) FROM flavors_history WHERE flavors_history.flavor_id = fh.flavor_id)) AS actual_time,
    'Infrastructure component change'::text AS change_description
FROM flavors_history fh

UNION ALL

-- Images
SELECT 'image'::text AS resource_type,
    ih.image_id AS resource_id,
    ih.name AS resource_name,
    ih.change_hash,
    ih.recorded_at,
    NULL::text AS project_name,
    NULL::text AS domain_name,
    COALESCE(((ih.raw_json ->> 'created_at'::text))::timestamp with time zone, ((ih.raw_json ->> 'updated_at'::text))::timestamp with time zone, ((ih.raw_json ->> 'created'::text))::timestamp with time zone, (SELECT min(images_history.recorded_at) FROM images_history WHERE images_history.image_id = ih.image_id)) AS actual_time,
    'Infrastructure component change'::text AS change_description
FROM images_history ih

UNION ALL

-- Hypervisors
SELECT 'hypervisor'::text AS resource_type,
    hh.hypervisor_id AS resource_id,
    hh.hostname AS resource_name,
    hh.change_hash,
    hh.recorded_at,
    NULL::text AS project_name,
    NULL::text AS domain_name,
    COALESCE(((hh.raw_json ->> 'created_at'::text))::timestamp with time zone, ((hh.raw_json ->> 'updated_at'::text))::timestamp with time zone, ((hh.raw_json ->> 'created'::text))::timestamp with time zone, (SELECT min(hypervisors_history.recorded_at) FROM hypervisors_history WHERE hypervisors_history.hypervisor_id = hh.hypervisor_id)) AS actual_time,
    'Infrastructure component change'::text AS change_description
FROM hypervisors_history hh

UNION ALL

-- Subnets
SELECT 'subnet'::text AS resource_type,
    sh.subnet_id AS resource_id,
    sh.name AS resource_name,
    sh.change_hash,
    sh.recorded_at,
    NULL::text AS project_name,
    NULL::text AS domain_name,
    COALESCE(((sh.raw_json ->> 'created_at'::text))::timestamp with time zone, ((sh.raw_json ->> 'updated_at'::text))::timestamp with time zone, ((sh.raw_json ->> 'created'::text))::timestamp with time zone, (SELECT min(subnets_history.recorded_at) FROM subnets_history WHERE subnets_history.subnet_id = sh.subnet_id)) AS actual_time,
    'Infrastructure component change'::text AS change_description
FROM subnets_history sh

UNION ALL

-- Routers
SELECT 'router'::text AS resource_type,
    rh.router_id AS resource_id,
    rh.name AS resource_name,
    rh.change_hash,
    rh.recorded_at,
    NULL::text AS project_name,
    NULL::text AS domain_name,
    COALESCE(((rh.raw_json ->> 'created_at'::text))::timestamp with time zone, ((rh.raw_json ->> 'updated_at'::text))::timestamp with time zone, ((rh.raw_json ->> 'created'::text))::timestamp with time zone, (SELECT min(routers_history.recorded_at) FROM routers_history WHERE routers_history.router_id = rh.router_id)) AS actual_time,
    'Infrastructure component change'::text AS change_description
FROM routers_history rh

UNION ALL

-- Snapshots
SELECT 'snapshot'::text AS resource_type,
    sh.snapshot_id AS resource_id,
    sh.name AS resource_name,
    sh.change_hash,
    sh.last_seen_at AS recorded_at,
    (sh.raw_json ->> 'project_name'::text) AS project_name,
    (sh.raw_json ->> 'domain_name'::text) AS domain_name,
    COALESCE(((sh.raw_json ->> 'created_at'::text))::timestamp without time zone) AS actual_time,
    'Snapshot lifecycle change'::text AS change_description
FROM snapshots_history sh

ORDER BY recorded_at DESC;

CREATE OR REPLACE VIEW v_recent_changes AS
SELECT
    resource_type,
    resource_id,
    resource_name,
    change_hash,
    recorded_at,
    project_name,
    domain_name,
    actual_time,
    change_description
FROM v_comprehensive_changes;