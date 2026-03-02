-- ---------------------------------------------------------------------------
-- Bulk Customer Onboarding — schema update
-- Target version: v1.38.1
-- Safe to re-run (IF NOT EXISTS / IF EXISTS guards throughout)
-- ---------------------------------------------------------------------------

-- Remove legacy field that was never a real OpenStack domain attribute
ALTER TABLE onboarding_customers
    DROP COLUMN IF EXISTS department_tag;

-- Projects: subscription_id + full quota columns (compute, network, storage)
ALTER TABLE onboarding_projects
    ADD COLUMN IF NOT EXISTS subscription_id       TEXT    DEFAULT '',
    ADD COLUMN IF NOT EXISTS quota_instances       INT     DEFAULT 10,
    ADD COLUMN IF NOT EXISTS quota_server_groups   INT     DEFAULT 10,
    ADD COLUMN IF NOT EXISTS quota_networks        INT     DEFAULT 10,
    ADD COLUMN IF NOT EXISTS quota_subnets         INT     DEFAULT 20,
    ADD COLUMN IF NOT EXISTS quota_routers         INT     DEFAULT 5,
    ADD COLUMN IF NOT EXISTS quota_ports           INT     DEFAULT 200,
    ADD COLUMN IF NOT EXISTS quota_floatingips     INT     DEFAULT 20,
    ADD COLUMN IF NOT EXISTS quota_security_groups INT     DEFAULT 10,
    ADD COLUMN IF NOT EXISTS quota_volumes         INT     DEFAULT 20,
    ADD COLUMN IF NOT EXISTS quota_snapshots       INT     DEFAULT 20;

-- Networks: kind/type/provider fields + allocation pool + external/shared flags
ALTER TABLE onboarding_networks
    ADD COLUMN IF NOT EXISTS network_kind          TEXT    DEFAULT 'physical_managed',
    ADD COLUMN IF NOT EXISTS network_type          TEXT    DEFAULT 'vlan',
    ADD COLUMN IF NOT EXISTS physical_network      TEXT    DEFAULT 'physnet1',
    ADD COLUMN IF NOT EXISTS is_external           BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS shared                BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS allocation_pool_start TEXT,
    ADD COLUMN IF NOT EXISTS allocation_pool_end   TEXT;

-- cidr is no longer required for physical_l2 networks
ALTER TABLE onboarding_networks
    ALTER COLUMN cidr DROP NOT NULL;

-- Users: allow caller-supplied password (blank = auto-generate at execute time)
ALTER TABLE onboarding_users
    ADD COLUMN IF NOT EXISTS user_password TEXT;

-- Execution audit log (appended during execution for visibility) + rerun counter
ALTER TABLE onboarding_batches
    ADD COLUMN IF NOT EXISTS execution_log  JSONB DEFAULT '[]';
ALTER TABLE onboarding_batches
    ADD COLUMN IF NOT EXISTS rerun_count    INT   DEFAULT 0;

-- Role permissions for onboarding feature
INSERT INTO role_permissions (role, resource, action) VALUES
    ('admin',     'onboarding', 'admin'),
    ('operator',  'onboarding', 'read'),
    ('operator',  'onboarding', 'create'),
    ('operator',  'onboarding', 'execute'),
    ('technical', 'onboarding', 'read'),
    ('viewer',    'onboarding', 'read')
ON CONFLICT (role, resource, action) DO NOTHING;
