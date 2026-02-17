-- =====================================================================
-- ACTIVITY LOG — Central audit trail for provisioning & domain mgmt
-- =====================================================================

CREATE TABLE IF NOT EXISTS activity_log (
    id              SERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor           TEXT NOT NULL,                          -- username who performed the action
    action          TEXT NOT NULL,                          -- create, delete, disable, enable, provision
    resource_type   TEXT NOT NULL,                          -- domain, project, server, volume, network, router, floating_ip, security_group, user, tenant
    resource_id     TEXT,                                   -- OpenStack resource UUID
    resource_name   TEXT,                                   -- human-readable name
    domain_id       TEXT,                                   -- parent domain UUID (if applicable)
    domain_name     TEXT,                                   -- parent domain name (if applicable)
    details         JSONB DEFAULT '{}',                     -- extra context (quotas, force flag, etc.)
    ip_address      TEXT,                                   -- client IP
    result          TEXT NOT NULL DEFAULT 'success',        -- success | failure
    error_message   TEXT                                    -- error detail if result=failure
);

CREATE INDEX IF NOT EXISTS idx_activity_log_timestamp     ON activity_log (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_activity_log_actor         ON activity_log (actor);
CREATE INDEX IF NOT EXISTS idx_activity_log_action        ON activity_log (action);
CREATE INDEX IF NOT EXISTS idx_activity_log_resource_type ON activity_log (resource_type);
CREATE INDEX IF NOT EXISTS idx_activity_log_domain_id     ON activity_log (domain_id);
CREATE INDEX IF NOT EXISTS idx_activity_log_result        ON activity_log (result);
