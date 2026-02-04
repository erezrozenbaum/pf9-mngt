-- Sample snapshot policies
INSERT INTO snapshot_policy_sets (name, is_global, policies, retention_map, priority, is_active, created_by, updated_by) VALUES
('Daily-Snapshots', true, ARRAY['daily']::text[], '{"daily": 7}'::jsonb, 1, true, 'admin', 'admin'),
('Weekly-Snapshots', true, ARRAY['weekly']::text[], '{"weekly": 30}'::jsonb, 2, true, 'admin', 'admin')
ON CONFLICT DO NOTHING;

-- Sample snapshot records
INSERT INTO snapshot_records (action, resource_id, resource_name, status, volume_id, snapshot_id) VALUES
('create', 'snap-001', 'Daily Backup 2026-02-04', 'success', 'vol-001', 'snap-001-id'),
('create', 'snap-002', 'Daily Backup 2026-02-04', 'success', 'vol-002', 'snap-002-id'),
('delete', 'snap-old', 'Old Snapshot', 'success', 'vol-001', 'snap-old-id')
ON CONFLICT DO NOTHING;

SELECT 'Snapshot Policies:' as info, COUNT(*) as count FROM snapshot_policy_sets
UNION ALL
SELECT 'Snapshot Records:' as info, COUNT(*) as count FROM snapshot_records;
