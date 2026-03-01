-- ============================================================
-- Migration: multi-network support for provisioning_jobs
-- Adds JSONB columns to persist the full networks config and
-- the list of networks actually created by each provisioning run.
-- ============================================================

-- networks_config  : the network list as submitted in the provision request
-- networks_created : summary of networks actually created (name, id, kind, vlan, subnet, etc.)
ALTER TABLE provisioning_jobs
    ADD COLUMN IF NOT EXISTS networks_config   JSONB DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS networks_created  JSONB DEFAULT '[]';

COMMENT ON COLUMN provisioning_jobs.networks_config IS
    'Full list of NetworkConfig objects from the ProvisionRequest (multi-network input)';
COMMENT ON COLUMN provisioning_jobs.networks_created IS
    'Ordered list of network summary dicts returned after creation (network_kind, name, network_id, subnet_id, vlan_id, subnet_cidr, etc.)';
