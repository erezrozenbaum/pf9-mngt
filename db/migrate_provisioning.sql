-- ============================================================
-- Provisioning tables  –  Customer onboarding workflow
-- ============================================================

-- A "job" represents one full customer provisioning run.
CREATE TABLE IF NOT EXISTS provisioning_jobs (
    id              BIGSERIAL PRIMARY KEY,
    job_id          TEXT      NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
    -- Input parameters
    domain_name     TEXT      NOT NULL,
    project_name    TEXT      NOT NULL,
    username        TEXT      NOT NULL,
    user_email      TEXT,
    user_role       TEXT      NOT NULL DEFAULT 'member',   -- member | admin | service
    -- Network configuration
    network_name    TEXT,
    network_type    TEXT      DEFAULT 'vlan',              -- vlan | flat | vxlan
    vlan_id         INTEGER,
    subnet_cidr     TEXT,
    gateway_ip      TEXT,
    dns_nameservers TEXT[]    DEFAULT ARRAY['8.8.8.8', '8.8.4.4'],
    -- Quota snapshot (JSONB for flexibility)
    quota_compute   JSONB     DEFAULT '{}',
    quota_network   JSONB     DEFAULT '{}',
    quota_storage   JSONB     DEFAULT '{}',
    -- Results
    status          TEXT      NOT NULL DEFAULT 'pending',  -- pending | running | completed | failed | partial
    domain_id       TEXT,
    project_id      TEXT,
    user_id         TEXT,
    network_id      TEXT,
    subnet_id       TEXT,
    security_group_id TEXT,
    -- Tracking
    created_by      TEXT      NOT NULL DEFAULT 'system',
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_provisioning_jobs_status     ON provisioning_jobs(status);
CREATE INDEX IF NOT EXISTS idx_provisioning_jobs_created_at ON provisioning_jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_provisioning_jobs_domain     ON provisioning_jobs(domain_name);

-- Individual steps within a provisioning job
CREATE TABLE IF NOT EXISTS provisioning_steps (
    id          BIGSERIAL PRIMARY KEY,
    job_id      TEXT        NOT NULL REFERENCES provisioning_jobs(job_id) ON DELETE CASCADE,
    step_number INTEGER     NOT NULL,
    step_name   TEXT        NOT NULL,  -- e.g. 'create_domain', 'create_project', ...
    description TEXT,
    status      TEXT        NOT NULL DEFAULT 'pending',  -- pending | running | completed | failed | skipped
    resource_id TEXT,                  -- OpenStack resource ID created by this step
    detail      JSONB       DEFAULT '{}',
    error       TEXT,
    started_at  TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_provisioning_steps_job ON provisioning_steps(job_id, step_number);

-- Add RBAC permissions for provisioning (idempotent)
INSERT INTO role_permissions (role, resource, action) VALUES
('admin', 'provisioning', 'read'),
('admin', 'provisioning', 'write'),
('admin', 'provisioning', 'admin'),
('superadmin', 'provisioning', 'read'),
('superadmin', 'provisioning', 'write'),
('superadmin', 'provisioning', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;
