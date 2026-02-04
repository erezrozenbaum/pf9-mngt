-- Sample infrastructure data
INSERT INTO servers (id, name, status) VALUES 
('srv-001', 'Test-VM-1', 'ACTIVE'),
('srv-002', 'Test-VM-2', 'SHUTOFF'),
('srv-003', 'Test-VM-3', 'ACTIVE')
ON CONFLICT DO NOTHING;

INSERT INTO volumes (id, name, status, size_gb) VALUES
('vol-001', 'Test-Volume-1', 'available', 100),
('vol-002', 'Test-Volume-2', 'in-use', 50),
('vol-003', 'Test-Volume-3', 'available', 250)
ON CONFLICT DO NOTHING;

-- Sample snapshot policies
INSERT INTO snapshot_policy_sets (name, is_global, policies, retention_map, priority, is_active, created_by, updated_by) VALUES
('Daily-Snapshots', true, '["daily"]'::text[], '{"daily": 7}'::jsonb, 1, true, 'admin', 'admin'),
('Weekly-Snapshots', true, '["weekly"]'::text[], '{"weekly": 30}'::jsonb, 2, true, 'admin', 'admin')
ON CONFLICT DO NOTHING;

-- Sample snapshot records
INSERT INTO snapshot_records (action, resource_type, resource_id, resource_name, status, volume_id, snapshot_id, error_details) VALUES
('create', 'snapshot', 'snap-001', 'Daily Backup 2026-02-04', 'success', 'vol-001', 'snap-001-id', NULL),
('create', 'snapshot', 'snap-002', 'Daily Backup 2026-02-04', 'success', 'vol-002', 'snap-002-id', NULL),
('delete', 'snapshot', 'snap-old', 'Old Snapshot', 'success', 'vol-001', 'snap-old-id', NULL)
ON CONFLICT DO NOTHING;

SELECT 'Servers:' as table_name, COUNT(*) as count FROM servers
UNION ALL
SELECT 'Volumes:' as table_name, COUNT(*) as count FROM volumes
UNION ALL
SELECT 'Snapshot Policies:' as table_name, COUNT(*) as count FROM snapshot_policy_sets
UNION ALL
SELECT 'Snapshot Records:' as table_name, COUNT(*) as count FROM snapshot_records;
