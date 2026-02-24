# Snapshot Automation System

## Overview

The Platform9 Management system includes a fully automated snapshot management solution that enables:

- **Policy-based snapshot creation** across Cinder volumes
- **Cross-tenant snapshot creation** using a dedicated service user
- **Retention management** with automatic cleanup of old snapshots
- **Cross-tenant snapshot policies** with exclusion rules
- **Compliance reporting** on snapshot adherence
- **Audit trail** for all snapshot operations

## Architecture

### Components

1. **Snapshot Scheduler** (`snapshots/snapshot_scheduler.py`)
   - Main orchestration loop running every 60 minutes (configurable)
   - Syncs policy sets from `snapshot_policy_rules.json`
   - Runs policy assignment and auto-snapshot subscripts

2. **Policy Assignment** (`snapshots/p9_snapshot_policy_assign.py`)
   - Scans all Cinder volumes across tenants
   - Applies metadata tags based on rules (opt-out model)
   - Tags volumes with `auto_snapshot`, `snapshot_policies`, and `retention_*` metadata

3. **Auto Snapshots** (`snapshots/p9_auto_snapshots.py`)
   - Processes volumes marked for auto-snapshotting
   - Creates snapshots with formatted names: `auto-{tenant}-{policy}-{server}-{volume}-{timestamp}`
   - Uses **dual-session architecture**: admin session for listing, service user session for creating
   - Deletes old snapshots based on retention policies
   - Generates audit records for all actions

4. **Snapshot Service User** (`snapshots/snapshot_service_user.py`)
   - Manages the snapshot service user account for cross-tenant operations
   - Ensures admin role assignment on each tenant project
   - Handles password retrieval (plaintext or Fernet-encrypted)
   - Per-run caching of role checks and user lookups

5. **Snapshot Management API** (`api/snapshot_management.py`)
   - REST endpoints for policy management
   - Compliance reporting endpoint
   - Audit trail queries

6. **Compliance UI** (`pf9-ui/src/components/SnapshotComplianceReport.tsx`)
   - Dashboard for compliance visualization
   - Filters by tenant, project, policy, and date range
   - Summary metrics and detailed records

### Dual-Session Architecture

The snapshot system uses two separate sessions to correctly scope snapshot operations:

```
┌─────────────────────────────────────────────────────────┐
│ Admin Session (service project scope)                    │
│  • List all volumes (all_tenants=1)                     │
│  • List snapshots for cleanup                           │
│  • Delete expired snapshots                             │
└─────────────────────────────────────────────────────────┘
              │
              ▼  For each tenant project:
┌─────────────────────────────────────────────────────────┐
│ Service User Session (tenant project scope)              │
│  • ensure_service_user() → admin role on project        │
│  • Authenticate as snapshot service user                │
│  • Create snapshot in correct tenant project            │
│  • Fallback: admin session (snapshot in service domain) │
└─────────────────────────────────────────────────────────┘
```

### Database

Snapshot system tables:
- `snapshot_policy_sets` - Policy set definitions
- `snapshot_assignments` - Tenant/project policy assignments
- `snapshot_exclusions` - Volumes/projects excluded from snapshots
- `snapshot_runs` - Audit records for each scheduler run (includes batch progress columns)
- `snapshot_records` - Individual snapshot operations (create/delete/skip)
- `snapshot_run_batches` - Per-batch progress tracking within a run (v1.26.0)
- `snapshot_quota_blocks` - Volumes skipped due to Cinder quota limits (v1.26.0)

## Policy Configuration

### Rules Format (`snapshots/snapshot_policy_rules.json`)

```json
[
  {
    "name": "Exclude lab / playground tenants",
    "priority": 10,
    "match": {
      "tenant_name": ["lab", "playground"]
    },
    "policies": [],
    "auto_snapshot": false
  },
  {
    "name": "Prod tenants - daily + 1st + 15th",
    "priority": 20,
    "match": {},
    "policies": ["daily_5", "monthly_1st", "monthly_15th"],
    "auto_snapshot": true,
    "retention": {
      "daily_5": 5,
      "monthly_1st": 1,
      "monthly_15th": 1
    }
  }
]
```

### Rule Matching (Opt-Out Model)

- All volumes are processed
- Rules are evaluated in priority order (lower = higher priority)
- **Exclusion rules** (auto_snapshot=false) skip volumes from snapshotting
- **Inclusion rules** (auto_snapshot=true) tag volumes with policy and retention metadata
- Matching criteria: `tenant_name`, `domain_name`, `volume_name`, `size_gb`, `bootable`, `metadata_equals`, `metadata_contains`

### Volume Metadata

After policy assignment, tagged volumes contain:
```
auto_snapshot: "true"
snapshot_policies: "daily_5,monthly_1st,monthly_15th"
retention_daily_5: "5"
retention_monthly_1st: "1"
retention_monthly_15th: "1"
```

## Current Status

✅ **FULLY FUNCTIONAL** — Cross-tenant snapshots enabled via service user

### All Features Working
✅ Policy-based volume tagging  
✅ **Cross-tenant snapshot creation** (snapshots in correct tenant projects)  
✅ Snapshot creation with tenant-aware naming  
✅ Retention and cleanup  
✅ Audit trail and database logging  
✅ Compliance API and UI  
✅ Policy set synchronization from rules  
✅ Service user role management per-project  
✅ Fernet-encrypted password support  
✅ Graceful fallback to admin session  
✅ **Quota-aware tenant batching** with configurable batch sizes and delays (v1.26.0)  
✅ **Cinder quota pre-check** — volumes blocked by quota are recorded, not failed (v1.26.0)  
✅ **Live progress tracking** — per-batch completion, progress percentage, ETA (v1.26.0)  
✅ **Snapshot Quota Forecast runbook** — proactive daily quota vs. policy analysis (v1.26.0)  

## Deployment

### Docker Service

```yaml
snapshot_worker:
  build:
    context: .
    dockerfile: snapshots/Dockerfile
  container_name: pf9_snapshot_worker
  environment:
    # Keystone Authentication
    PF9_AUTH_URL: ${PF9_AUTH_URL}
    PF9_USERNAME: ${PF9_USERNAME}
    PF9_PASSWORD: ${PF9_PASSWORD}
    PF9_USER_DOMAIN: ${PF9_USER_DOMAIN:-Default}
    PF9_PROJECT_NAME: ${PF9_PROJECT_NAME:-service}
    PF9_PROJECT_DOMAIN: ${PF9_PROJECT_DOMAIN:-Default}
    
    # Snapshot Service User (cross-tenant)
    SNAPSHOT_SERVICE_USER_EMAIL: ${SNAPSHOT_SERVICE_USER_EMAIL}
    SNAPSHOT_SERVICE_USER_PASSWORD: ${SNAPSHOT_SERVICE_USER_PASSWORD:-}
    SNAPSHOT_PASSWORD_KEY: ${SNAPSHOT_PASSWORD_KEY}
    SNAPSHOT_USER_PASSWORD_ENCRYPTED: ${SNAPSHOT_USER_PASSWORD_ENCRYPTED}
    
    # Database
    PF9_DB_HOST: db
    PF9_DB_NAME: ${PF9_DB_NAME:-pf9_mgmt}
    PF9_DB_USER: ${PF9_DB_USER:-pf9}
    PF9_DB_PASSWORD: ${PF9_DB_PASSWORD}
    
    # Scheduler
    SNAPSHOT_SCHEDULER_ENABLED: ${SNAPSHOT_SCHEDULER_ENABLED:-true}
    POLICY_ASSIGN_INTERVAL_MINUTES: ${POLICY_ASSIGN_INTERVAL_MINUTES:-60}
    AUTO_SNAPSHOT_INTERVAL_MINUTES: ${AUTO_SNAPSHOT_INTERVAL_MINUTES:-60}
    AUTO_SNAPSHOT_DRY_RUN: ${AUTO_SNAPSHOT_DRY_RUN:-false}
      # Batching (v1.26.0)
      AUTO_SNAPSHOT_BATCH_SIZE: ${AUTO_SNAPSHOT_BATCH_SIZE:-20}
      AUTO_SNAPSHOT_BATCH_DELAY: ${AUTO_SNAPSHOT_BATCH_DELAY:-5.0}
  restart: always
```

### Environment Variables

Add to `.env`:

```bash
# Required: Service user credentials (choose one option)
SNAPSHOT_SERVICE_USER_EMAIL=<your-snapshot-user@your-domain.com>

# Option A: Plaintext password
SNAPSHOT_SERVICE_USER_PASSWORD=<service_user_password>

# Option B: Encrypted password
SNAPSHOT_PASSWORD_KEY=<Fernet encryption key>
SNAPSHOT_USER_PASSWORD_ENCRYPTED=<Fernet encrypted password>
```

See [Snapshot Service User Guide](SNAPSHOT_SERVICE_USER.md) for detailed setup instructions.

## Usage

### Modify Policies

Edit `snapshots/snapshot_policy_rules.json` and the scheduler will sync automatically on next run.

### On-Demand Snapshot Pipeline ("Sync & Snapshot Now")

In addition to the hourly scheduler, admins can trigger the full snapshot pipeline on demand via the UI or API:

**UI**: On the **Delete & Restore** tab → Screen 1, click the **🔄 Sync & Snapshot Now** button. A real-time progress bar shows each step (policy assignment → inventory sync → auto snapshots → inventory sync).

**API**: `POST /snapshot/run-now` (requires `snapshots:admin` — admin or superadmin role)

```bash
curl -X POST http://localhost:8000/snapshot/run-now \
  -H "Authorization: Bearer <token>"
```

Response (202 Accepted):
```json
{
  "job_id": "abc-123",
  "status": "running",
  "message": "Snapshot pipeline started. Poll /snapshot/run-now/status for progress."
}
```

**Poll status**: `GET /snapshot/run-now/status` (requires `snapshots:read`)

```json
{
  "job_id": "abc-123",
  "status": "completed",
  "triggered_by": "admin@example.com",
  "started_at": "2026-02-15T10:00:00+00:00",
  "finished_at": "2026-02-15T10:05:32+00:00",
  "steps": [
    { "key": "policy_assign", "label": "Policy Assignment", "status": "completed" },
    { "key": "rvtools_pre", "label": "Inventory Sync (pre-snapshot)", "status": "completed" },
    { "key": "auto_snapshots", "label": "Auto Snapshots", "status": "completed" },
    { "key": "rvtools_post", "label": "Inventory Sync (post-snapshot)", "status": "completed" }
  ]
}
```

> **Note**: Only one on-demand run can execute at a time. A second request while one is running returns 409 Conflict.

### Query Compliance

**API Endpoint**: `GET /api/snapshot/compliance`

Parameters:
- `days`: Look back N days (default: 7)
- `tenant_id`: Filter by tenant
- `project_id`: Filter by project
- `policy_name`: Filter by policy

**UI**: Navigate to **Snapshot Policies** → **Compliance** tab

### Audit Trail

**Database**: Query `snapshot_records` and `snapshot_runs` tables

```sql
-- Last 10 snapshot operations
SELECT * FROM snapshot_records ORDER BY created_at DESC LIMIT 10;

-- Snapshot run summary
SELECT * FROM snapshot_runs ORDER BY created_at DESC LIMIT 10;
```

## Troubleshooting

### Snapshots Not Creating

**Check logs**:
```bash
docker logs pf9_snapshot_worker
```

**Verify policy rules**:
```bash
cat snapshots/snapshot_policy_rules.json
```

**Check volume metadata**:
```bash
# Via OpenStack CLI
cinder metadata-list
```

### Snapshots in Wrong Project

**Symptom**: Snapshots created in service domain instead of volume's tenant

**Check**:
```bash
docker logs pf9_snapshot_worker 2>&1 | grep -E "SERVICE_USER|service user|Falling back"
```

**Causes**:
- Service user password not configured in `.env`
- Service user (configured via `SNAPSHOT_SERVICE_USER_EMAIL`) not created in Platform9
- Admin session lacks permission to assign roles

**Fix**: See [Snapshot Service User Guide](SNAPSHOT_SERVICE_USER.md) for setup instructions

### Database Connection Issues

Verify environment variables:
```bash
docker exec pf9_snapshot_worker env | grep PF9_DB
```

Check PostgreSQL:
```bash
psql -h localhost -U pf9 -d pf9_mgmt -c "SELECT COUNT(*) FROM snapshot_records;"
```

## Operations

### Verify Cross-Tenant Snapshots

```bash
# Check snapshot worker logs for service user activity
docker logs pf9_snapshot_worker 2>&1 | grep -E "SERVICE_USER|service user session"

# Expected: lines showing admin role grants and service user authentication per project
```

### Disable Cross-Tenant Mode

To fall back to admin-only mode (snapshots in service domain):

```bash
# Option 1: Disable service user via env var
SNAPSHOT_SERVICE_USER_DISABLED=true

# Option 2: Remove service user password from .env
# (system will gracefully fall back to admin session)
```

## References

- [Snapshot Service User Guide](SNAPSHOT_SERVICE_USER.md)
- [Policy Rules Format](../snapshots/snapshot_policy_rules.json)
- [Snapshot Scheduler](../snapshots/snapshot_scheduler.py)
- [Policy Assignment](../snapshots/p9_snapshot_policy_assign.py)
- [Auto Snapshots](../snapshots/p9_auto_snapshots.py)
- [Service User Module](../snapshots/snapshot_service_user.py)
- [API Endpoints](../api/snapshot_management.py)
