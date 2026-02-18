-- Migration: Add is_default column to nav_groups
-- Allows one group to be designated as the "default" group that
-- auto-opens and shows its page on login.

ALTER TABLE nav_groups ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT false;

-- Ensure at most one default group (application-level enforced, but add comment)
COMMENT ON COLUMN nav_groups.is_default IS 'If true, this group auto-opens on login and its first item page is shown. Only one group should be default.';
