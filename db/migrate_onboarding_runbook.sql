-- ---------------------------------------------------------------------------
-- Bulk Customer Onboarding — database migration
-- Target version: v1.38.0
-- ---------------------------------------------------------------------------

-- ── Top-level batch ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS onboarding_batches (
    id                  SERIAL PRIMARY KEY,
    batch_id            UUID NOT NULL DEFAULT gen_random_uuid(),
    batch_name          TEXT NOT NULL,
    uploaded_by         TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'validating',
    -- validation_errors: [{row, sheet, field, message}, ...]
    validation_errors   JSONB DEFAULT '[]'::jsonb,
    -- dry_run_result: {summary:{...}, items:[{resource_type, name, action, reason}]}
    dry_run_result      JSONB,
    -- approval
    approval_status     TEXT DEFAULT 'not_submitted',
    approved_by         TEXT,
    approved_at         TIMESTAMPTZ,
    rejection_comment   TEXT,
    -- execution summary
    execution_result    JSONB,
    -- counts (filled after parse)
    total_customers     INT DEFAULT 0,
    total_projects      INT DEFAULT 0,
    total_networks      INT DEFAULT 0,
    total_users         INT DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_onboarding_batches_batch_id
    ON onboarding_batches (batch_id);

-- ── Customers (domains) ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS onboarding_customers (
    id              SERIAL PRIMARY KEY,
    batch_id        UUID NOT NULL REFERENCES onboarding_batches(batch_id) ON DELETE CASCADE,
    domain_name     TEXT NOT NULL,
    display_name    TEXT,
    description     TEXT,
    contact_email   TEXT,
    department_tag  TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    error_msg       TEXT,
    pcd_domain_id   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_onboarding_customers_batch
    ON onboarding_customers (batch_id);
CREATE INDEX IF NOT EXISTS idx_onboarding_customers_domain
    ON onboarding_customers (batch_id, domain_name);

-- ── Projects ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS onboarding_projects (
    id              SERIAL PRIMARY KEY,
    batch_id        UUID NOT NULL REFERENCES onboarding_batches(batch_id) ON DELETE CASCADE,
    customer_id     INT REFERENCES onboarding_customers(id) ON DELETE CASCADE,
    domain_name     TEXT NOT NULL,
    project_name    TEXT NOT NULL,
    description     TEXT,
    quota_vcpu      INT DEFAULT 20,
    quota_ram_mb    INT DEFAULT 51200,
    quota_disk_gb   INT DEFAULT 1000,
    status          TEXT NOT NULL DEFAULT 'pending',
    error_msg       TEXT,
    pcd_project_id  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_onboarding_projects_batch
    ON onboarding_projects (batch_id);
CREATE INDEX IF NOT EXISTS idx_onboarding_projects_customer
    ON onboarding_projects (customer_id);

-- ── Networks ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS onboarding_networks (
    id              SERIAL PRIMARY KEY,
    batch_id        UUID NOT NULL REFERENCES onboarding_batches(batch_id) ON DELETE CASCADE,
    project_id      INT REFERENCES onboarding_projects(id) ON DELETE CASCADE,
    domain_name     TEXT NOT NULL,
    project_name    TEXT NOT NULL,
    network_name    TEXT NOT NULL,
    cidr            TEXT NOT NULL,
    gateway         TEXT,
    dns1            TEXT DEFAULT '8.8.8.8',
    vlan_id         INT,
    dhcp_enabled    BOOLEAN DEFAULT TRUE,
    status          TEXT NOT NULL DEFAULT 'pending',
    error_msg       TEXT,
    pcd_network_id  TEXT,
    pcd_subnet_id   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_onboarding_networks_batch
    ON onboarding_networks (batch_id);
CREATE INDEX IF NOT EXISTS idx_onboarding_networks_project
    ON onboarding_networks (project_id);

-- ── Users ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS onboarding_users (
    id                  SERIAL PRIMARY KEY,
    batch_id            UUID NOT NULL REFERENCES onboarding_batches(batch_id) ON DELETE CASCADE,
    project_id          INT REFERENCES onboarding_projects(id) ON DELETE CASCADE,
    domain_name         TEXT NOT NULL,
    project_name        TEXT NOT NULL,
    username            TEXT NOT NULL,
    email               TEXT,
    role                TEXT NOT NULL DEFAULT 'member',
    send_welcome_email  BOOLEAN DEFAULT TRUE,
    status              TEXT NOT NULL DEFAULT 'pending',
    error_msg           TEXT,
    pcd_user_id         TEXT,
    temp_password       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_onboarding_users_batch
    ON onboarding_users (batch_id);
CREATE INDEX IF NOT EXISTS idx_onboarding_users_project
    ON onboarding_users (project_id);

-- ── updated_at triggers ────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION onboarding_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_ob_batches_updated')
    THEN
        CREATE TRIGGER trg_ob_batches_updated
            BEFORE UPDATE ON onboarding_batches
            FOR EACH ROW EXECUTE FUNCTION onboarding_set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_ob_customers_updated')
    THEN
        CREATE TRIGGER trg_ob_customers_updated
            BEFORE UPDATE ON onboarding_customers
            FOR EACH ROW EXECUTE FUNCTION onboarding_set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_ob_projects_updated')
    THEN
        CREATE TRIGGER trg_ob_projects_updated
            BEFORE UPDATE ON onboarding_projects
            FOR EACH ROW EXECUTE FUNCTION onboarding_set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_ob_networks_updated')
    THEN
        CREATE TRIGGER trg_ob_networks_updated
            BEFORE UPDATE ON onboarding_networks
            FOR EACH ROW EXECUTE FUNCTION onboarding_set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_ob_users_updated')
    THEN
        CREATE TRIGGER trg_ob_users_updated
            BEFORE UPDATE ON onboarding_users
            FOR EACH ROW EXECUTE FUNCTION onboarding_set_updated_at();
    END IF;
END $$;

-- Role permissions for onboarding feature
INSERT INTO role_permissions (role, resource, action) VALUES
    ('admin',     'onboarding', 'admin'),
    ('operator',  'onboarding', 'read'),
    ('operator',  'onboarding', 'create'),
    ('operator',  'onboarding', 'execute'),
    ('technical', 'onboarding', 'read'),
    ('viewer',    'onboarding', 'read')
ON CONFLICT (role, resource, action) DO NOTHING;
