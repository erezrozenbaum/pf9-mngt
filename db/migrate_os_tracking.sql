-- Migration: Add OS tracking columns to servers and images tables
-- This tracks image_id, os_distro, and os_version for each VM,
-- enabling SPLA licensing and OS distribution monitoring.

-- Add OS columns to servers
ALTER TABLE servers ADD COLUMN IF NOT EXISTS image_id TEXT;
ALTER TABLE servers ADD COLUMN IF NOT EXISTS os_distro TEXT;
ALTER TABLE servers ADD COLUMN IF NOT EXISTS os_version TEXT;

-- Add same columns to servers_history
ALTER TABLE servers_history ADD COLUMN IF NOT EXISTS image_id TEXT;
ALTER TABLE servers_history ADD COLUMN IF NOT EXISTS os_distro TEXT;
ALTER TABLE servers_history ADD COLUMN IF NOT EXISTS os_version TEXT;

-- Add OS columns to images (from Glance metadata properties)
ALTER TABLE images ADD COLUMN IF NOT EXISTS os_distro TEXT;
ALTER TABLE images ADD COLUMN IF NOT EXISTS os_version TEXT;
ALTER TABLE images ADD COLUMN IF NOT EXISTS os_type TEXT;

-- Add OS columns to images_history
ALTER TABLE images_history ADD COLUMN IF NOT EXISTS os_distro TEXT;
ALTER TABLE images_history ADD COLUMN IF NOT EXISTS os_version TEXT;
ALTER TABLE images_history ADD COLUMN IF NOT EXISTS os_type TEXT;

-- Indexes for OS-based queries
CREATE INDEX IF NOT EXISTS idx_servers_os_distro ON servers(os_distro);
CREATE INDEX IF NOT EXISTS idx_servers_image_id ON servers(image_id);
CREATE INDEX IF NOT EXISTS idx_images_os_distro ON images(os_distro);
