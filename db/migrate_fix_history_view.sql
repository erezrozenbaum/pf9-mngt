-- Migration: Fix v_comprehensive_changes to use history-stored names
-- instead of relying solely on LEFT JOINs to live tables.
-- When a resource is deleted, the live-table JOIN returns NULL.
-- Uses COALESCE(NULLIF(history.name,''), NULLIF(live.name,''), fallback)
-- so empty-string names (common for ports/volumes) also get a fallback.

CREATE OR REPLACE VIEW v_comprehensive_changes AS
-- Servers
SELECT 'server' AS resource_type,
       h.server_id AS resource_id,
       COALESCE(NULLIF(h.name,''), NULLIF(s.name,'')) AS resource_name,
       h.change_hash, h.recorded_at,
       p.name AS project_name,
       d.name AS domain_name,
       NULL::TIMESTAMPTZ AS actual_time,
       'Server state/history change' AS change_description
FROM servers_history h
LEFT JOIN servers s ON h.server_id = s.id
LEFT JOIN projects p ON COALESCE(h.project_id, s.project_id) = p.id
LEFT JOIN domains d ON p.domain_id = d.id

UNION ALL
-- Volumes (fallback to volume_type + truncated ID when name is empty)
SELECT 'volume', h.volume_id,
       COALESCE(NULLIF(h.name,''), NULLIF(v.name,''), COALESCE(h.volume_type, 'vol') || ' (' || LEFT(h.volume_id, 8) || ')'),
       h.change_hash, h.recorded_at,
       p.name, d.name, NULL,
       'Volume state/history change'
FROM volumes_history h
LEFT JOIN volumes v ON h.volume_id = v.id
LEFT JOIN projects p ON COALESCE(h.project_id, v.project_id) = p.id
LEFT JOIN domains d ON p.domain_id = d.id

UNION ALL
-- Snapshots (has project_name/domain_name directly)
SELECT 'snapshot', h.snapshot_id,
       COALESCE(NULLIF(h.name,''), NULLIF(s.name,'')),
       h.change_hash, h.recorded_at,
       COALESCE(NULLIF(h.project_name,''), s.project_name),
       COALESCE(NULLIF(h.domain_name,''), s.domain_name),
       NULL,
       'Snapshot state/history change'
FROM snapshots_history h
LEFT JOIN snapshots s ON h.snapshot_id = s.id

UNION ALL
-- Security Groups (has project_name/domain_name directly)
SELECT 'security_group', h.security_group_id,
       COALESCE(NULLIF(h.name,''), NULLIF(sg.name,'')),
       h.change_hash, h.recorded_at,
       COALESCE(NULLIF(h.project_name,''), sg.project_name),
       COALESCE(NULLIF(h.domain_name,''), sg.domain_name),
       NULL,
       'Security group state/history change'
FROM security_groups_history h
LEFT JOIN security_groups sg ON h.security_group_id = sg.id

UNION ALL
-- Security Group Rules
SELECT 'security_group_rule', h.security_group_rule_id,
       COALESCE(sg.name, '') || ' / ' || COALESCE(h.direction, '') || ' ' || COALESCE(h.protocol, 'any'),
       h.change_hash, h.recorded_at,
       COALESCE(sg.project_name, p.name),
       COALESCE(sg.domain_name, d.name),
       NULL,
       'Security group rule state/history change'
FROM security_group_rules_history h
LEFT JOIN security_groups sg ON h.security_group_id = sg.id
LEFT JOIN projects p ON COALESCE(h.project_id, sg.project_id) = p.id
LEFT JOIN domains d ON p.domain_id = d.id

UNION ALL
-- Networks
SELECT 'network', h.network_id,
       COALESCE(NULLIF(h.name,''), NULLIF(n.name,'')),
       h.change_hash, h.recorded_at,
       p.name, d.name, NULL,
       'Network state/history change'
FROM networks_history h
LEFT JOIN networks n ON h.network_id = n.id
LEFT JOIN projects p ON COALESCE(h.project_id, n.project_id) = p.id
LEFT JOIN domains d ON p.domain_id = d.id

UNION ALL
-- Subnets (fallback to CIDR when name is empty)
SELECT 'subnet', h.subnet_id,
       COALESCE(NULLIF(h.name,''), NULLIF(sn.name,''), COALESCE(h.cidr, sn.cidr, 'subnet (' || LEFT(h.subnet_id, 8) || ')')),
       h.change_hash, h.recorded_at,
       p.name, d.name, NULL,
       'Subnet state/history change'
FROM subnets_history h
LEFT JOIN subnets sn ON h.subnet_id = sn.id
LEFT JOIN networks net ON COALESCE(h.network_id, sn.network_id) = net.id
LEFT JOIN projects p ON net.project_id = p.id
LEFT JOIN domains d ON p.domain_id = d.id

UNION ALL
-- Ports (fallback to device_owner + mac_address when name is empty)
SELECT 'port', h.port_id,
       COALESCE(NULLIF(h.name,''), NULLIF(p2.name,''),
         CASE WHEN COALESCE(h.device_owner, p2.device_owner, '') <> ''
              THEN COALESCE(h.device_owner, p2.device_owner) || ' (' || LEFT(COALESCE(h.mac_address, p2.mac_address, h.port_id), 17) || ')'
              ELSE 'port (' || LEFT(h.port_id, 8) || ')'
         END),
       h.change_hash, h.recorded_at,
       pr.name, dm.name, NULL,
       'Port state/history change'
FROM ports_history h
LEFT JOIN ports p2 ON h.port_id = p2.id
LEFT JOIN projects pr ON COALESCE(h.project_id, p2.project_id) = pr.id
LEFT JOIN domains dm ON pr.domain_id = dm.id

UNION ALL
-- Floating IPs (use floating_ip as name)
SELECT 'floating_ip', h.floating_ip_id,
       COALESCE(NULLIF(h.floating_ip,''), NULLIF(fi.floating_ip,''), 'fip (' || LEFT(h.floating_ip_id, 8) || ')'),
       h.change_hash, h.recorded_at,
       pr.name, dm.name, NULL,
       'Floating IP state/history change'
FROM floating_ips_history h
LEFT JOIN floating_ips fi ON h.floating_ip_id = fi.id
LEFT JOIN projects pr ON COALESCE(h.project_id, fi.project_id) = pr.id
LEFT JOIN domains dm ON pr.domain_id = dm.id

UNION ALL
-- Routers
SELECT 'router', h.router_id,
       COALESCE(NULLIF(h.name,''), NULLIF(rt.name,'')),
       h.change_hash, h.recorded_at,
       p.name, d.name, NULL,
       'Router state/history change'
FROM routers_history h
LEFT JOIN routers rt ON h.router_id = rt.id
LEFT JOIN projects p ON COALESCE(h.project_id, rt.project_id) = p.id
LEFT JOIN domains d ON p.domain_id = d.id

UNION ALL
-- Domains
SELECT 'domain', h.domain_id,
       COALESCE(NULLIF(h.name,''), NULLIF(dom.name,'')),
       h.change_hash, h.recorded_at,
       NULL, COALESCE(NULLIF(h.name,''), NULLIF(dom.name,'')), NULL,
       'Domain state/history change'
FROM domains_history h
LEFT JOIN domains dom ON h.domain_id = dom.id

UNION ALL
-- Projects
SELECT 'project', h.project_id,
       COALESCE(NULLIF(h.name,''), NULLIF(proj.name,'')),
       h.change_hash, h.recorded_at,
       COALESCE(NULLIF(h.name,''), NULLIF(proj.name,'')),
       d.name, NULL,
       'Project state/history change'
FROM projects_history h
LEFT JOIN projects proj ON h.project_id = proj.id
LEFT JOIN domains d ON COALESCE(h.domain_id, proj.domain_id) = d.id

UNION ALL
-- Flavors
SELECT 'flavor', h.flavor_id,
       COALESCE(NULLIF(h.name,''), NULLIF(fl.name,'')),
       h.change_hash, h.recorded_at,
       NULL, NULL, NULL,
       'Flavor state/history change'
FROM flavors_history h
LEFT JOIN flavors fl ON h.flavor_id = fl.id

UNION ALL
-- Images
SELECT 'image', h.image_id,
       COALESCE(NULLIF(h.name,''), NULLIF(img.name,'')),
       h.change_hash, h.recorded_at,
       NULL, NULL, NULL,
       'Image state/history change'
FROM images_history h
LEFT JOIN images img ON h.image_id = img.id

UNION ALL
-- Hypervisors
SELECT 'hypervisor', h.hypervisor_id,
       COALESCE(NULLIF(h.hostname,''), NULLIF(hv.hostname,'')),
       h.change_hash, h.recorded_at,
       NULL, NULL, NULL,
       'Hypervisor state/history change'
FROM hypervisors_history h
LEFT JOIN hypervisors hv ON h.hypervisor_id = hv.id

UNION ALL
-- Users
SELECT 'user', h.user_id,
       COALESCE(NULLIF(h.name,''), NULLIF(u.name,'')),
       h.change_hash, h.recorded_at,
       NULL,
       d.name, NULL,
       'User state/history change'
FROM users_history h
LEFT JOIN users u ON h.user_id = u.id
LEFT JOIN domains d ON COALESCE(h.domain_id, u.domain_id) = d.id

UNION ALL
-- Roles
SELECT 'role', h.role_id,
       COALESCE(NULLIF(h.name,''), NULLIF(r.name,'')),
       h.change_hash, h.recorded_at,
       NULL,
       d.name, NULL,
       'Role state/history change'
FROM roles_history h
LEFT JOIN roles r ON h.role_id = r.id
LEFT JOIN domains d ON COALESCE(h.domain_id, r.domain_id) = d.id

UNION ALL
-- Deletions (fallback to type + truncated ID when name is empty)
SELECT dh.resource_type AS resource_type,
       dh.resource_id,
       COALESCE(NULLIF(dh.resource_name, ''), dh.resource_type || ' (' || LEFT(dh.resource_id, 8) || ')') AS resource_name,
       'deleted-' || dh.resource_id AS change_hash,
       dh.deleted_at AS recorded_at,
       dh.project_name,
       dh.domain_name,
       dh.deleted_at AS actual_time,
       'Resource deleted' AS change_description
FROM deletions_history dh;
