-- Migration: Fix operator (and viewer) permissions
-- Issue: operator role had 'write' but no 'read' for networks/flavors, causing 403 on GET requests
-- Issue: operator and viewer roles had no 'users' permission for PF9 inventory users
-- Date: 2026-02-18

-- Add missing read permissions for resources where operator only had write
INSERT INTO role_permissions (role, resource, action)
VALUES 
  ('operator', 'networks', 'read'),
  ('operator', 'flavors', 'read'),
  ('operator', 'snapshot_assignments', 'read'),
  ('operator', 'snapshot_exclusions', 'read'),
  ('operator', 'users', 'read'),
  ('viewer', 'users', 'read')
ON CONFLICT (role, resource, action) DO NOTHING;
