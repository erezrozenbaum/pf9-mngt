# Platform9 Management Database Schema

This document provides a comprehensive overview of the PostgreSQL database schema used by the Platform9 Management Portal.

## Overview

The database follows a multi-tenant architecture supporting OpenStack infrastructure management with comprehensive history tracking, user management, and operational features.

### Core Design Principles
- **Multi-tenancy**: Domain → Project → Resource hierarchy
- **History tracking**: Every core resource has `_history` tables for change auditing
- **UUID-based IDs**: All resources use Text UUIDs for OpenStack compatibility
- **JSONB storage**: Raw API responses preserved for flexibility
- **Timestamped records**: Creation, update, and last-seen tracking

---

## Core Infrastructure Tables

### Domains
The top-level organizational unit in OpenStack's hierarchical model.

```sql
CREATE TABLE domains (
    id          TEXT PRIMARY KEY,           -- OpenStack domain UUID
    name        TEXT NOT NULL,              -- Human-readable domain name
    raw_json    JSONB,                      -- Full OpenStack domain response
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Projects (Tenants)  
Project/tenant isolation within domains.

```sql
CREATE TABLE projects (
    id           TEXT PRIMARY KEY,          -- OpenStack project UUID
    name         TEXT NOT NULL,             -- Project display name
    domain_id    TEXT REFERENCES domains(id),
    raw_json     JSONB,                     -- Full OpenStack project response
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Users
User accounts from Keystone identity service.

```sql
CREATE TABLE users (
    id            TEXT PRIMARY KEY,         -- Keystone user UUID
    name          TEXT NOT NULL,            -- Username
    email         TEXT,                     -- User email address
    enabled       BOOLEAN DEFAULT true,    -- Account enabled status
    domain_id     TEXT REFERENCES domains(id),
    description   TEXT,                     -- User description
    default_project_id TEXT REFERENCES projects(id),
    password_expires_at TIMESTAMPTZ,       -- Password expiry
    created_at    TIMESTAMPTZ,             -- Account creation time
    last_login    TIMESTAMPTZ,             -- Last successful login
    raw_json      JSONB,                   -- Full Keystone user object
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for user management
CREATE INDEX idx_users_domain_id ON users(domain_id);
CREATE INDEX idx_users_enabled ON users(enabled);
CREATE INDEX idx_users_email ON users(email);
```

### Roles
Role definitions from Keystone RBAC system.

```sql
CREATE TABLE roles (
    id            TEXT PRIMARY KEY,         -- Keystone role UUID
    name          TEXT NOT NULL UNIQUE,     -- Role name (admin, member, etc.)
    description   TEXT,                     -- Role description
    domain_id     TEXT REFERENCES domains(id),
    raw_json      JSONB,                   -- Full Keystone role object
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## Compute Resources

### Hypervisors
Physical compute nodes hosting virtual machines.

```sql
CREATE TABLE hypervisors (
    id               TEXT PRIMARY KEY,      -- Nova hypervisor UUID
    hostname         TEXT,                  -- Physical host FQDN
    hypervisor_type  TEXT,                 -- KVM, VMware, etc.
    vcpus            INTEGER,              -- Total vCPU capacity
    memory_mb        INTEGER,              -- Total RAM in MB
    local_gb         INTEGER,              -- Local storage in GB
    state            TEXT,                 -- up, down, maintenance
    status           TEXT,                 -- enabled, disabled
    running_vms      INTEGER DEFAULT 0,    -- Current VM count
    created_at       TIMESTAMPTZ,          -- Hypervisor registration time
    raw_json         JSONB,                -- Full Nova hypervisor response
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Flavors
VM sizing templates defining compute, memory, and storage allocations.

```sql
CREATE TABLE flavors (
    id            TEXT PRIMARY KEY,         -- Nova flavor UUID
    name          TEXT,                     -- Flavor name (m1.small, etc.)
    vcpus         INTEGER,                  -- vCPU count
    ram_mb        INTEGER,                  -- RAM allocation in MB  
    disk_gb       INTEGER,                  -- Root disk size in GB
    ephemeral_gb  INTEGER,                  -- Ephemeral disk in GB
    swap_mb       INTEGER,                  -- Swap space in MB
    is_public     BOOLEAN,                  -- Public visibility
    raw_json      JSONB,                   -- Full Nova flavor response
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Images  
VM base images and snapshots available for instance creation.

```sql
CREATE TABLE images (
    id            TEXT PRIMARY KEY,         -- Glance image UUID
    name          TEXT,                     -- Image name
    status        TEXT,                     -- active, queued, saving, etc.
    visibility    TEXT,                     -- public, private, shared
    protected     BOOLEAN,                  -- Deletion protection
    size_bytes    BIGINT,                   -- Image file size
    disk_format   TEXT,                     -- qcow2, raw, vmdk, etc.
    container_format TEXT,                  -- bare, ovf, ova, etc.
    checksum      TEXT,                     -- Image integrity hash
    os_distro     TEXT,                     -- ubuntu, centos, windows, etc.
    os_version    TEXT,                     -- 20.04, 7, 2019, etc.
    os_type       TEXT,                     -- linux, windows
    min_disk      INTEGER,                  -- Minimum disk requirement GB
    min_ram       INTEGER,                  -- Minimum RAM requirement MB
    created_at    TIMESTAMPTZ,             -- Image creation time
    updated_at    TIMESTAMPTZ,             -- Last update time
    raw_json      JSONB,                   -- Full Glance image response
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for image management
CREATE INDEX idx_images_os_distro ON images(os_distro);
```

### Servers (Virtual Machines)
Running virtual machine instances.

```sql
CREATE TABLE servers (
    id               TEXT PRIMARY KEY,      -- Nova instance UUID
    name             TEXT,                  -- VM display name
    project_id       TEXT REFERENCES projects(id),
    status           TEXT,                  -- ACTIVE, SHUTOFF, ERROR, etc.
    vm_state         TEXT,                  -- active, stopped, building, etc.
    flavor_id        TEXT,                  -- Flavor UUID reference
    hypervisor_hostname TEXT,              -- Physical host assignment
    image_id         TEXT,                  -- Source image UUID
    os_distro        TEXT,                  -- Detected OS distribution
    os_version       TEXT,                  -- Detected OS version
    created_at       TIMESTAMPTZ,          -- VM creation time
    raw_json         JSONB,                -- Full Nova server response
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for server management
CREATE INDEX idx_servers_os_distro ON servers(os_distro);
CREATE INDEX idx_servers_image_id ON servers(image_id);
```

---

## Storage Resources

### Volumes
Block storage volumes for VM attachment.

```sql
CREATE TABLE volumes (
    id               TEXT PRIMARY KEY,      -- Cinder volume UUID
    name             TEXT,                  -- Volume display name
    project_id       TEXT REFERENCES projects(id),
    size_gb          INTEGER,              -- Volume size in GB
    status           TEXT,                  -- available, in-use, error, etc.
    volume_type      TEXT,                 -- Volume type/backend
    server_id        TEXT,                 -- Attached server UUID
    bootable         BOOLEAN,              -- Boot volume capability
    created_at       TIMESTAMPTZ,          -- Volume creation time
    raw_json         JSONB,                -- Full Cinder volume response
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for attachment queries
CREATE INDEX idx_volumes_server_id ON volumes(server_id);
```

### Snapshots
Point-in-time volume snapshots for backup and restore.

```sql
CREATE TABLE snapshots (
    id            TEXT PRIMARY KEY,         -- Cinder snapshot UUID
    name          TEXT,                     -- Snapshot display name
    description   TEXT,                     -- Snapshot description
    project_id    TEXT,                     -- Owning project UUID
    project_name  TEXT,                     -- Cached project name
    tenant_name   TEXT,                     -- Cached tenant name  
    domain_name   TEXT,                     -- Cached domain name
    domain_id     TEXT,                     -- Domain UUID
    volume_id     TEXT REFERENCES volumes(id),
    size_gb       INTEGER,                  -- Snapshot size in GB
    status        TEXT,                     -- available, creating, error, etc.
    created_at    TIMESTAMPTZ,             -- Snapshot creation time
    updated_at    TIMESTAMPTZ,             -- Last status update
    raw_json      JSONB,                   -- Full Cinder snapshot response
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## Network Resources

### Networks
Virtual networks providing L2 connectivity.

```sql
CREATE TABLE networks (
    id             TEXT PRIMARY KEY,        -- Neutron network UUID
    name           TEXT,                    -- Network display name
    project_id     TEXT REFERENCES projects(id),
    status         TEXT,                    -- ACTIVE, DOWN, BUILD, ERROR
    admin_state_up BOOLEAN,                 -- Administrative state
    is_shared      BOOLEAN,                 -- Cross-tenant sharing
    is_external    BOOLEAN,                 -- External network flag
    raw_json       JSONB,                  -- Full Neutron network response
    last_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_networks_status ON networks(status);
```

### Subnets  
L3 IP address pools within networks.

```sql
CREATE TABLE subnets (
    id           TEXT PRIMARY KEY,          -- Neutron subnet UUID
    name         TEXT,                      -- Subnet display name
    network_id   TEXT REFERENCES networks(id),
    cidr         TEXT,                      -- IP subnet in CIDR notation
    gateway_ip   TEXT,                      -- Default gateway IP
    enable_dhcp  BOOLEAN,                   -- DHCP service enabled
    raw_json     JSONB,                    -- Full Neutron subnet response
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Routers
L3 routers providing inter-network connectivity.

```sql
CREATE TABLE routers (
    id            TEXT PRIMARY KEY,         -- Neutron router UUID
    name          TEXT,                     -- Router display name
    project_id    TEXT REFERENCES projects(id),
    external_net_id TEXT,                  -- External network UUID
    raw_json      JSONB,                   -- Full Neutron router response
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Ports
Network interface attachments for VMs and network services.

```sql
CREATE TABLE ports (
    id            TEXT PRIMARY KEY,         -- Neutron port UUID
    name          TEXT,                     -- Port display name
    network_id    TEXT REFERENCES networks(id),
    project_id    TEXT REFERENCES projects(id),
    device_id     TEXT,                     -- Attached device UUID
    device_owner  TEXT,                     -- Device type (compute:nova, etc.)
    mac_address   TEXT,                     -- MAC address assignment
    status        TEXT,                     -- ACTIVE, DOWN, BUILD
    ip_addresses  JSONB,                    -- Fixed IP assignments
    raw_json      JSONB,                   -- Full Neutron port response
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_ports_status ON ports(status);
```

### Floating IPs
Externally routable IP addresses for VM access.

```sql
CREATE TABLE floating_ips (
    id            TEXT PRIMARY KEY,         -- Neutron floating IP UUID
    floating_ip   TEXT,                     -- External IP address
    fixed_ip      TEXT,                     -- Associated internal IP
    port_id       TEXT REFERENCES ports(id),
    project_id    TEXT REFERENCES projects(id),
    router_id     TEXT REFERENCES routers(id),
    status        TEXT,                     -- ACTIVE, DOWN, ERROR
    raw_json      JSONB,                   -- Full Neutron FloatingIP response
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## History and Auditing

All core resource tables have corresponding `_history` tables for change tracking:

- `domains_history`
- `projects_history` 
- `users_history`
- `roles_history`
- `hypervisors_history`
- `flavors_history`
- `images_history`
- `servers_history`
- `volumes_history`
- `snapshots_history`
- `networks_history`
- `subnets_history`
- `routers_history`
- `ports_history`
- `floating_ips_history`

### History Table Pattern
Each history table follows this structure:

```sql
CREATE TABLE {resource}_history (
    id           BIGSERIAL PRIMARY KEY,    -- Internal history record ID
    {resource}_id TEXT NOT NULL,           -- Original resource UUID
    -- ... all resource fields ...
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_hash  TEXT NOT NULL,            -- Deduplication hash
    raw_json     JSONB                    -- Full resource data snapshot
);

-- Standard indexes for history queries
CREATE INDEX idx_{resource}_history_{resource}_id ON {resource}_history({resource}_id);
CREATE INDEX idx_{resource}_history_recorded_at ON {resource}_history(recorded_at);
CREATE INDEX idx_{resource}_history_change_hash ON {resource}_history({resource}_id, change_hash);
```

### Inventory Runs
Tracks data collection cycles for compliance and drift detection.

```sql
CREATE TABLE inventory_runs (
    id               BIGSERIAL PRIMARY KEY, -- Internal run ID
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at      TIMESTAMPTZ,          -- Completion timestamp
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    status           TEXT,                  -- success, failure, partial
    source           TEXT,                  -- Data collection source
    host_name        TEXT,                  -- Collection host
    duration_seconds INTEGER,               -- Run duration
    notes            TEXT                   -- Additional context
);
```

---

## Operational Features

### Backup Config
Database backup schedule and retention policy.

```sql
CREATE TABLE backup_config (
    id                   SERIAL PRIMARY KEY,
    enabled              BOOLEAN NOT NULL DEFAULT false,
    nfs_path             TEXT NOT NULL DEFAULT '/backups',
    schedule_type        TEXT NOT NULL DEFAULT 'daily'
                         CHECK (schedule_type IN ('daily', 'weekly')),
    schedule_time_utc    TEXT NOT NULL DEFAULT '02:00',
    schedule_day_of_week INTEGER NOT NULL DEFAULT 0,
    retention_count      INTEGER NOT NULL DEFAULT 7,
    retention_days       INTEGER NOT NULL DEFAULT 30,
    last_backup_at       TIMESTAMPTZ,
    last_ldap_backup_at  TIMESTAMPTZ,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Backup History
Individual database backup and restore job records. Added in v1.74.5; integrity columns added v1.93.11; `integrity_hash` added v1.93.21.

```sql
CREATE TABLE backup_history (
    id               SERIAL PRIMARY KEY,
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'running', 'completed', 'failed', 'deleted')),
    backup_type      TEXT NOT NULL DEFAULT 'manual'
                     CHECK (backup_type IN ('manual', 'scheduled', 'restore')),
    backup_target    TEXT NOT NULL DEFAULT 'database'
                     CHECK (backup_target IN ('database', 'ldap')),
    file_name        TEXT,
    file_path        TEXT,
    file_size_bytes  BIGINT,
    duration_seconds FLOAT,
    initiated_by     TEXT,
    error_message    TEXT,
    started_at       TIMESTAMPTZ,
    completed_at     TIMESTAMPTZ,
    -- Integrity validation
    integrity_status     TEXT CHECK (integrity_status IN ('pending', 'valid', 'invalid', 'skipped')),
    integrity_checked_at TIMESTAMPTZ,
    integrity_notes      TEXT,
    integrity_hash       VARCHAR(64),  -- SHA-256 hex digest (H7, v1.93.21)
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Snapshot Policies
Automated backup policy definitions.

```sql
CREATE TABLE snapshot_policies (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,          -- Policy display name
    description     TEXT,                   -- Policy description
    schedule_cron   TEXT NOT NULL,          -- Cron schedule expression
    retention_days  INTEGER NOT NULL,       -- Backup retention period
    domain_filter   TEXT[],                -- Target domain names
    tenant_filter   TEXT[],                -- Target tenant names
    volume_filters  JSONB,                 -- Volume selection criteria
    enabled         BOOLEAN DEFAULT true,   -- Policy active state
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    created_by      TEXT,                   -- Creator username
    last_run_at     TIMESTAMPTZ,           -- Last execution time
    next_run_at     TIMESTAMPTZ            -- Next scheduled execution
);
```

### Snapshot Jobs
Individual backup job execution records.

```sql
CREATE TABLE snapshot_jobs (
    id              BIGSERIAL PRIMARY KEY,
    policy_id       BIGINT REFERENCES snapshot_policies(id),
    status          TEXT NOT NULL,          -- pending, running, completed, failed
    started_at      TIMESTAMPTZ,           -- Job start time
    finished_at     TIMESTAMPTZ,           -- Job completion time
    total_volumes   INTEGER,                -- Volumes to process
    successful_snapshots INTEGER,           -- Successful backups
    failed_snapshots INTEGER,               -- Failed backups
    error_message   TEXT,                   -- Failure details
    execution_log   TEXT,                   -- Detailed execution log
    created_at      TIMESTAMPTZ DEFAULT now()
);
```

### User Sessions
Active authentication sessions and tokens.

```sql
CREATE TABLE user_sessions (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL,          -- Keystone user UUID
    username        TEXT NOT NULL,          -- Username for quick lookup
    token_hash      TEXT UNIQUE NOT NULL,   -- JWT token hash
    expires_at      TIMESTAMPTZ NOT NULL,   -- Token expiration
    created_at      TIMESTAMPTZ DEFAULT now(),
    last_activity   TIMESTAMPTZ DEFAULT now(),
    ip_address      INET,                   -- Client IP address
    user_agent      TEXT,                   -- Client browser/app
    revoked         BOOLEAN DEFAULT false   -- Manual revocation flag
);

-- Indexes for session management  
CREATE INDEX idx_user_sessions_token_hash ON user_sessions(token_hash);
CREATE INDEX idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX idx_user_sessions_expires_at ON user_sessions(expires_at);
```

### Ops Copilot
AI assistant conversation history and configuration.

```sql
CREATE TABLE copilot_config (
    id                    SERIAL PRIMARY KEY,
    backend               TEXT NOT NULL,      -- openai, anthropic, ollama, builtin
    openai_api_key        TEXT,              -- OpenAI API key
    openai_model          TEXT,              -- GPT model name
    anthropic_api_key     TEXT,              -- Anthropic API key  
    anthropic_model       TEXT,              -- Claude model name
    ollama_url            TEXT,              -- Ollama server URL
    ollama_model          TEXT,              -- Local model name
    redact_sensitive      BOOLEAN DEFAULT true,
    system_prompt         TEXT,              -- LLM system prompt
    max_history_per_user  INTEGER DEFAULT 200,
    created_at            TIMESTAMPTZ DEFAULT now(),
    updated_at            TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE copilot_history (
    id              BIGSERIAL PRIMARY KEY,
    username        TEXT NOT NULL,          -- User who asked question
    question        TEXT NOT NULL,          -- Original user question
    answer          TEXT NOT NULL,          -- Copilot response
    intent          TEXT,                   -- Matched intent category
    backend         TEXT NOT NULL,          -- LLM backend used
    model           TEXT,                   -- Specific model used
    confidence      REAL,                   -- Intent confidence score
    tokens_used     INTEGER,                -- Token consumption
    response_time_ms INTEGER,               -- Response latency
    feedback_rating INTEGER,                -- User feedback (1-5)
    feedback_comment TEXT,                  -- User feedback text
    created_at      TIMESTAMPTZ DEFAULT now(),
    context_data    JSONB                   -- Additional context used
);

-- Indexes for conversation retrieval
CREATE INDEX idx_copilot_history_username ON copilot_history(username);
CREATE INDEX idx_copilot_history_created_at ON copilot_history(created_at);
```

### Drift Detection
Infrastructure change detection and compliance monitoring.

```sql
CREATE TABLE drift_rules (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,          -- Rule display name
    description     TEXT,                   -- Rule description
    resource_type   TEXT NOT NULL,          -- server, volume, network, etc.
    field_name      TEXT NOT NULL,          -- Resource field to monitor
    rule_type       TEXT NOT NULL,          -- change_detection, threshold, etc.
    severity        TEXT NOT NULL,          -- critical, warning, info
    enabled         BOOLEAN DEFAULT true,   -- Rule active state
    config          JSONB,                  -- Rule-specific configuration
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE drift_events (
    id              BIGSERIAL PRIMARY KEY,
    resource_type   TEXT NOT NULL,          -- Resource type affected
    resource_id     TEXT NOT NULL,          -- Resource UUID
    resource_name   TEXT,                   -- Resource display name
    field_name      TEXT NOT NULL,          -- Changed field name
    old_value       TEXT,                   -- Previous field value
    new_value       TEXT,                   -- Current field value
    severity        TEXT NOT NULL,          -- Event severity level
    rule_name       TEXT,                   -- Triggering rule name
    detected_at     TIMESTAMPTZ DEFAULT now(),
    acknowledged    BOOLEAN DEFAULT false,  -- Manual acknowledgment
    acknowledged_by TEXT,                   -- Acknowledging user
    acknowledged_at TIMESTAMPTZ,           -- Acknowledgment timestamp
    domain_name     TEXT,                   -- Resource domain
    tenant_name     TEXT                    -- Resource tenant
);

-- Indexes for drift monitoring
CREATE INDEX idx_drift_events_resource_type ON drift_events(resource_type);
CREATE INDEX idx_drift_events_detected_at ON drift_events(detected_at);
CREATE INDEX idx_drift_events_acknowledged ON drift_events(acknowledged);
```

---

## Tenant Portal Foundation (v1.84.0)

Five tables + one view added for the tenant self-service portal. The portal connects to PostgreSQL as `tenant_portal_role` (minimal grants, subject to RLS) — not the admin `pf9` user.

### Row-Level Security Policy

RLS is enabled on five inventory tables. Every tenant portal DB transaction must first call:
```sql
SET LOCAL app.tenant_project_ids   = '<csv>';   -- e.g. 'proj-1,proj-2'
SET LOCAL app.tenant_region_ids    = '<csv>';
SET LOCAL app.tenant_keystone_user_id = '<uid>';
SET LOCAL app.tenant_cp_id         = '<cp>';
```
The RLS policies enforce `project_id = ANY(string_to_array(...))` — so a misconfigured session sees zero rows rather than too many.

Tables with RLS enabled: `servers`, `volumes`, `snapshots`, `snapshot_records`, `restore_jobs`.

### tenant_portal_access
Per-user, per-CP access allowlist (default-deny). No entry = no login.
```sql
CREATE TABLE tenant_portal_access (
    id               BIGSERIAL    PRIMARY KEY,
    keystone_user_id TEXT         NOT NULL,
    control_plane_id TEXT         NOT NULL REFERENCES pf9_control_planes(id),
    enabled          BOOLEAN      NOT NULL DEFAULT false,
    mfa_required     BOOLEAN      NOT NULL DEFAULT false,
    notes            TEXT,
    granted_by       TEXT,
    granted_at       TIMESTAMPTZ,
    revoked_by       TEXT,
    revoked_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (keystone_user_id, control_plane_id)
);
```
Redis mirrors: `tenant:allowed:<cp>:<uid>` (TTL 300 s), `tenant:blocked:<cp>:<uid>`.

### tenant_portal_mfa
TOTP / email-OTP state per user per CP. RLS enabled.
```sql
CREATE TABLE tenant_portal_mfa (
    keystone_user_id TEXT         NOT NULL,
    control_plane_id TEXT         NOT NULL REFERENCES pf9_control_planes(id),
    mfa_type         TEXT         NOT NULL DEFAULT 'email_otp',
    totp_secret_enc  TEXT,        -- Fernet-encrypted TOTP seed
    email            TEXT,
    last_used_at     TIMESTAMPTZ,
    failed_attempts  INT          NOT NULL DEFAULT 0,
    locked_until     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (keystone_user_id, control_plane_id)
);
```

### tenant_portal_branding
Per-CP runtime-configurable branding. Updated via `PUT /api/admin/tenant-portal/branding/{cp_id}` without pod restart.
```sql
CREATE TABLE tenant_portal_branding (
    control_plane_id TEXT         PRIMARY KEY REFERENCES pf9_control_planes(id),
    company_name     VARCHAR(255) NOT NULL DEFAULT 'Cloud Portal',
    logo_url         TEXT,
    favicon_url      TEXT,
    primary_color    CHAR(7)      DEFAULT '#1A73E8',
    accent_color     CHAR(7)      DEFAULT '#F29900',
    support_email    TEXT,
    support_url      TEXT,
    welcome_message  TEXT,
    footer_text      TEXT,
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);
```

### tenant_action_log
Permanent, tamper-evident audit trail for all tenant portal activity.
```sql
CREATE TABLE tenant_action_log (
    id               BIGSERIAL    PRIMARY KEY,
    keystone_user_id TEXT         NOT NULL,
    username         VARCHAR(255) NOT NULL,
    control_plane_id TEXT         NOT NULL,
    action           VARCHAR(100) NOT NULL,
    resource_type    VARCHAR(50),
    resource_id      TEXT,
    project_id       TEXT,
    region_id        TEXT,
    ip_address       INET,
    user_agent       TEXT,
    timestamp        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    success          BOOLEAN      NOT NULL DEFAULT true,
    details          JSONB
);
CREATE INDEX idx_tenant_action_log_user_ts ON tenant_action_log (keystone_user_id, timestamp DESC);
CREATE INDEX idx_tenant_action_log_cp_ts   ON tenant_action_log (control_plane_id, timestamp DESC);
```

### runbook_project_tags
Maps runbooks to Keystone project IDs so tenant users only see runbooks relevant to their projects.
```sql
CREATE TABLE runbook_project_tags (
    runbook_name TEXT NOT NULL REFERENCES runbooks(name) ON DELETE CASCADE,
    project_id   TEXT NOT NULL,
    PRIMARY KEY (runbook_name, project_id)
);
```

---

## Intelligence & SLA (v1.85.0 / v1.88.0)

### operational_insights
De-duplicated operational insight feed populated by the `intelligence_worker` and `sla_worker`.
```sql
CREATE TABLE operational_insights (
    id              BIGSERIAL PRIMARY KEY,
    type            TEXT NOT NULL,           -- capacity_storage | waste_idle_vm | waste_unattached_volume |
                                             --   waste_old_snapshots | risk_snapshot_gap | risk_health_decline |
                                             --   risk_unack_drift | sla_risk
    severity        TEXT NOT NULL,           -- critical | high | medium | low
    entity_type     TEXT NOT NULL,           -- tenant | vm | volume | snapshot | project
    entity_id       TEXT NOT NULL,
    entity_name     TEXT,
    title           TEXT NOT NULL,
    message         TEXT NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'open',  -- open | acknowledged | snoozed | resolved | suppressed
    acknowledged_by TEXT,
    acknowledged_at TIMESTAMPTZ,
    snooze_until    TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- De-duplication: only one active insight per (type, entity_type, entity_id)
CREATE UNIQUE INDEX idx_insights_active_dedup
    ON operational_insights (type, entity_type, entity_id)
    WHERE status IN ('open','acknowledged','snoozed');
```

### insight_recommendations (v1.88.0)
Actionable recommendations attached to open insights — generated by the intelligence worker Phase 2 engines. Idle-VM waste insights get resize/runbook recommendations; risk insights auto-create tickets.
```sql
CREATE TABLE insight_recommendations (
    id               SERIAL PRIMARY KEY,
    insight_id       INT NOT NULL REFERENCES operational_insights(id) ON DELETE CASCADE,
    action_type      TEXT NOT NULL,              -- runbook | resize | cleanup | migrate | ticket
    runbook_id       INT REFERENCES runbooks(id),
    action_payload   JSONB NOT NULL DEFAULT '{}',
    estimated_impact TEXT,
    status           TEXT NOT NULL DEFAULT 'pending',  -- pending | executed | dismissed
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    executed_at      TIMESTAMPTZ,
    execution_id     INT REFERENCES runbook_executions(id)
);
CREATE INDEX idx_recs_insight ON insight_recommendations(insight_id);
CREATE INDEX idx_recs_status  ON insight_recommendations(status);
```

**Lifecycle:**
- `pending` — generated, awaiting human or automated action
- `executed` — runbook/resize ran; `executed_at` and optionally `execution_id` set
- `dismissed` — operator dismissed; never re-generated for same insight in same cycle

### sla_tier_templates
Pre-defined SLA tier templates (bronze / silver / gold / custom).
```sql
CREATE TABLE sla_tier_templates (
    tier                TEXT PRIMARY KEY,    -- bronze | silver | gold | custom
    display_name        TEXT NOT NULL,
    uptime_pct          NUMERIC(6,3),        -- e.g. 99.9
    rto_hours           NUMERIC(8,2),        -- Recovery Time Objective
    rpo_hours           NUMERIC(8,2),        -- Recovery Point Objective
    mtta_hours          NUMERIC(8,2),        -- Mean Time To Acknowledge
    mttr_hours          NUMERIC(8,2),        -- Mean Time To Resolve
    backup_freq_hours   NUMERIC(8,2)         -- Max hours between backups
);
```

### sla_commitments
Per-tenant SLA commitment with date range (NULL `effective_to` = currently active).
```sql
CREATE TABLE sla_commitments (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    tier            TEXT NOT NULL REFERENCES sla_tier_templates(tier),
    uptime_pct      NUMERIC(6,3),
    rto_hours       NUMERIC(8,2),
    rpo_hours       NUMERIC(8,2),
    mtta_hours      NUMERIC(8,2),
    mttr_hours      NUMERIC(8,2),
    backup_freq_hours NUMERIC(8,2),
    effective_from  DATE NOT NULL DEFAULT CURRENT_DATE,
    effective_to    DATE,
    notes           TEXT,
    created_by      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, effective_from)
);
```

### sla_compliance_monthly
Monthly SLA KPI measurements per tenant. `region_id = ''` (empty string) is the all-region aggregate row.
```sql
CREATE TABLE sla_compliance_monthly (
    tenant_id           TEXT NOT NULL,
    month               DATE NOT NULL,           -- First day of the month
    region_id           TEXT NOT NULL DEFAULT '', -- '' = all-region aggregate
    uptime_pct          NUMERIC(6,3),
    rto_worst_hours     NUMERIC(8,2),
    rpo_worst_hours     NUMERIC(8,2),
    mtta_hours          NUMERIC(8,2),
    mttr_hours          NUMERIC(8,2),
    backup_success_pct  NUMERIC(6,3),
    breached_fields     TEXT[],                  -- e.g. ARRAY['uptime_pct','rto_worst_hours']
    at_risk_fields      TEXT[],
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, month, region_id)
);
```

### tenant_cp_view
Safe projection of `pf9_control_planes` — hides `username`, `password_enc`, and internal credentials. Grants `SELECT` to `tenant_portal_role`.
```sql
CREATE OR REPLACE VIEW tenant_cp_view AS
    SELECT id, name, auth_url, is_enabled, display_color, tags
    FROM   pf9_control_planes
    WHERE  is_enabled = TRUE;
```

## MSP Business Value Layer (v1.90.0)

### msp_contract_entitlements
Per-tenant contracted resource limits for Revenue Leakage detection. Two partial unique indexes handle NULL `region_id` (global limit) vs non-NULL (region-specific limit). `unit_price` column added in v1.92.0 for revenue leakage dollar estimates in the Executive Dashboard.

```sql
CREATE TABLE msp_contract_entitlements (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    resource        TEXT NOT NULL,        -- vcpu | ram_gb | storage_gb | floating_ip
    limit_value     NUMERIC(12,3) NOT NULL,
    unit_price      DECIMAL(10,4),        -- (v1.92.0) nullable; enables revenue_leakage_monthly in executive summary
    region_id       TEXT,                 -- NULL = applies to all regions
    effective_from  DATE NOT NULL DEFAULT CURRENT_DATE,
    effective_to    DATE,                 -- NULL = open-ended (currently active)
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Region-specific entitlement: one active row per (tenant, resource, effective_from, region_id)
CREATE UNIQUE INDEX uq_entitlements_active_with_region
    ON msp_contract_entitlements (tenant_id, resource, effective_from, region_id)
    WHERE region_id IS NOT NULL;
-- Global entitlement: one active row per (tenant, resource, effective_from) with no region
CREATE UNIQUE INDEX uq_entitlements_active_global
    ON msp_contract_entitlements (tenant_id, resource, effective_from)
    WHERE region_id IS NULL;
```

### msp_labor_rates
Per-insight-type labor rate configuration for QBR ROI calculations. Seeded with 8 common types at $150/hr.

```sql
CREATE TABLE msp_labor_rates (
    insight_type    TEXT PRIMARY KEY,   -- waste_idle_vm | waste_orphan_volume | capacity_storage | ...
    label           TEXT NOT NULL,
    hours_saved     NUMERIC(8,2) NOT NULL DEFAULT 2.0,
    hourly_rate_usd NUMERIC(10,2) NOT NULL DEFAULT 150.0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Seeded types** (8 rows): `waste_idle_vm`, `waste_orphan_volume`, `waste_orphan_snapshot`, `waste_orphan_fip`, `capacity_storage`, `risk_snapshot_gap`, `leakage_overconsumption`, `leakage_ghost`.

### psa_webhook_config
Outbound PSA/ITSM webhook configuration. Auth header is Fernet-encrypted at rest.

```sql
CREATE TABLE psa_webhook_config (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    webhook_url     TEXT NOT NULL,          -- must start with http:// or https://
    auth_header     TEXT,                   -- Fernet-encrypted "Bearer ..." or "Key: Value"
    min_severity    TEXT NOT NULL DEFAULT 'high',  -- info|medium|high|critical
    filter_types    JSONB NOT NULL DEFAULT '[]',   -- [] = all types allowed
    filter_regions  JSONB NOT NULL DEFAULT '[]',   -- [] = all regions allowed
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Webhook firing rules**: Triggered from `intelligence_worker/engines/base.py` `upsert_insight()` on new inserts (`xmax=0`) when severity is `high` or `critical`. Per-config `min_severity`, `filter_types`, and `filter_regions` conditions are all applied before firing.

---

## Enriched Views

### Volume Attachments
Provides legacy compatibility for volume attachment queries.

```sql
CREATE OR REPLACE VIEW v_volumes_full AS
SELECT 
    v.id,
    v.name AS volume_name,
    v.status,
    v.size_gb,
    v.volume_type,
    v.bootable,
    v.created_at,
    p.id AS tenant_id,
    p.name AS tenant_name,
    d.id AS domain_id,
    d.name AS domain_name,
    v.raw_json->'attachments'->0->>'server_id' AS server_id,
    (SELECT srv.name FROM servers srv 
     WHERE srv.id = (v.raw_json->'attachments'->0->>'server_id')) AS server_name,
    v.raw_json->'attachments'->0->>'device' AS device,
    v.raw_json->'attachments'->0->>'host_name' AS attach_host
FROM volumes v
LEFT JOIN projects p ON p.id = v.project_id
LEFT JOIN domains d ON d.id = p.domain_id;
```

---

## Indexes and Performance

Key indexes for query performance:

### Resource Lookups
- Primary keys (UUIDs) on all tables
- Foreign key references automatically indexed
- `last_seen_at` for data freshness queries

### Multi-tenant Filtering  
- `project_id` indexes on all tenant-scoped resources
- `domain_id` indexes for domain-level queries

### Status and State Queries
- `status` indexes on servers, volumes, networks, ports
- `enabled` indexes on users and policies

### Time-based Queries
- `created_at` and `updated_at` for temporal analysis
- `recorded_at` on all history tables
- `expires_at` on sessions and tokens

### Search and Filtering
- `os_distro` indexes for OS-based queries
- Composite indexes for common filter combinations
- JSONB GIN indexes where appropriate for flexible queries

### Hot-Path Compound Indexes (added v1.83.50)
High-frequency query paths identified from dashboard and API profiling:

```sql
-- Project-scoped VM listing with status filter (most common dashboard query)
CREATE INDEX idx_servers_project_status      ON servers(project_id, status);
-- Hypervisor drill-down
CREATE INDEX idx_servers_hypervisor          ON servers(hypervisor_hostname);
-- Staleness detection by collector
CREATE INDEX idx_servers_last_seen           ON servers(last_seen_at DESC);
-- Project-scoped volume listing
CREATE INDEX idx_volumes_project_status      ON volumes(project_id, status);
-- Project-scoped snapshot listing
CREATE INDEX idx_snapshots_project_created   ON snapshots(project_id, created_at DESC);
-- Volume → snapshot reverse lookup
CREATE INDEX idx_snapshots_volume_id         ON snapshots(volume_id);
-- Active restore jobs dashboard (status + time order)
CREATE INDEX idx_restore_jobs_status_created ON restore_jobs(status, created_at DESC);
-- Domain-scoped drift summary
CREATE INDEX idx_drift_events_domain         ON drift_events(domain_id);
CREATE INDEX idx_drift_events_domain_ack     ON drift_events(domain_id, acknowledged);
-- Per-VM snapshot history
CREATE INDEX idx_snapshot_records_vm_created ON snapshot_records(vm_id, created_at DESC);
```

---

## Referential Integrity Constraints (added v1.83.50)

FK constraints added to enforce data integrity without scanning existing rows (`NOT VALID`):

```sql
-- Prevent restore jobs for non-existent projects
ALTER TABLE restore_jobs
    ADD CONSTRAINT fk_restore_jobs_project
    FOREIGN KEY (project_id) REFERENCES projects(id)
    ON DELETE RESTRICT NOT VALID;

-- Preserve snapshot history when a VM is deleted (null vm_id rather than block delete)
ALTER TABLE snapshot_records
    ADD CONSTRAINT fk_snapshot_records_server
    FOREIGN KEY (vm_id) REFERENCES servers(id)
    ON DELETE SET NULL NOT VALID;
```

`NOT VALID` means existing rows are not scanned during the migration — only new inserts and updates are validated. Run `VALIDATE CONSTRAINT` off-hours if you need full historical enforcement.

---

## Migration Strategy

Database schema changes are managed through versioned migration files in `/db/migrate_*.sql`:

- Each migration has a descriptive filename with version
- Migrations are idempotent and can be safely re-run  
- `inventory_runs` table tracks schema version progression
- Rollback scripts provided for critical changes

Current schema version: **v1.83.50** (April 2026)