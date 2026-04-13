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