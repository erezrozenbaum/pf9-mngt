-- Migration: Add missing OS-tracking and metadata columns
-- Adds os_distro, os_version, os_type to images
-- Adds image_id, os_distro, os_version to servers
-- Adds running_vms, created_at to hypervisors
-- Idempotent: safe to re-run

-- Images: OS metadata columns
ALTER TABLE images ADD COLUMN IF NOT EXISTS os_distro TEXT;
ALTER TABLE images ADD COLUMN IF NOT EXISTS os_version TEXT;
ALTER TABLE images ADD COLUMN IF NOT EXISTS os_type TEXT;
ALTER TABLE images ADD COLUMN IF NOT EXISTS min_disk INTEGER;
ALTER TABLE images ADD COLUMN IF NOT EXISTS min_ram INTEGER;
CREATE INDEX IF NOT EXISTS idx_images_os_distro ON images(os_distro);

-- Servers: OS tracking + image reference
ALTER TABLE servers ADD COLUMN IF NOT EXISTS image_id TEXT;
ALTER TABLE servers ADD COLUMN IF NOT EXISTS os_distro TEXT;
ALTER TABLE servers ADD COLUMN IF NOT EXISTS os_version TEXT;
CREATE INDEX IF NOT EXISTS idx_servers_os_distro ON servers(os_distro);
CREATE INDEX IF NOT EXISTS idx_servers_image_id ON servers(image_id);

-- Hypervisors: running VM count + created_at
ALTER TABLE hypervisors ADD COLUMN IF NOT EXISTS running_vms INTEGER DEFAULT 0;
ALTER TABLE hypervisors ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
