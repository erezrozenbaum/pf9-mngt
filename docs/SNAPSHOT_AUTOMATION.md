# Snapshot Automation System

## Overview

The Platform9 Management system includes an automated snapshot management solution that enables:

- **Policy-based snapshot creation** across Cinder volumes
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
   - Deletes old snapshots based on retention policies
   - Generates audit records for all actions

4. **Snapshot Management API** (`api/snapshot_management.py`)
   - REST endpoints for policy management
   - Compliance reporting endpoint
   - Audit trail queries

5. **Compliance UI** (`pf9-ui/src/components/SnapshotComplianceReport.tsx`)
   - Dashboard for compliance visualization
   - Filters by tenant, project, policy, and date range
   - Summary metrics and detailed records

### Database

Snapshot system tables:
- `snapshot_policy_sets` - Policy set definitions
- `snapshot_assignments` - Tenant/project policy assignments
- `snapshot_exclusions` - Volumes/projects excluded from snapshots
- `snapshot_runs` - Audit records for each scheduler run
- `snapshot_records` - Individual snapshot operations (create/delete/skip)

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

⚠️ **PARTIAL FUNCTIONALITY** — Awaiting cross-tenant access

### Working Features
✅ Policy-based volume tagging
✅ Snapshot creation with tenant-aware naming
✅ Retention and cleanup
✅ Audit trail and database logging
✅ Compliance API and UI
✅ Policy set synchronization from rules

### Pending Features (Expected: ~1 month)
⏳ **Snapshots in correct tenant projects**

Currently, snapshots are created in the **service/admin domain** because the service admin user (`erez@ccc.co.il`) lacks roles in tenant projects. This is a multi-tenant security boundary issue:

- **Problem**: Keystone project-scoped tokens require the user to have a role in that project
- **Current State**: Service admin can list all volumes but can only create snapshots in own project
- **Solution**: Once the platform admin gains cross-tenant access (tenant admin role assignment in progress), snapshots will be created in the **original tenant project** where the volume resides

### Timeline

1. **Now**: System is fully functional for metadata tagging and audit tracking
2. **In ~1 month**: Tenant access configured → snapshots move to correct projects
3. **Activation**: Change `docker-compose.yml` `restart: "no"` back to `restart: unless-stopped` and restart services

## Deployment

### Docker Service

```yaml
snapshot_worker:
  build:
    context: .
    dockerfile: snapshots/Dockerfile
  environment:
    # Keystone
    PF9_AUTH_URL: http://keystone:5000/v3
    PF9_USERNAME: erez@ccc.co.il
    PF9_PASSWORD: <password>
    PF9_USER_DOMAIN: ccc.co.il
    PF9_PROJECT_NAME: service
    PF9_PROJECT_DOMAIN: Default
    
    # Database
    PF9_DB_HOST: db
    PF9_DB_NAME: pf9_mgmt
    PF9_DB_USER: pf9
    PF9_DB_PASSWORD: <password>
    
    # Scheduler
    SNAPSHOT_SCHEDULER_ENABLED: true
    POLICY_ASSIGN_INTERVAL_MINUTES: 60
    AUTO_SNAPSHOT_INTERVAL_MINUTES: 60
    
    # Config
    POLICY_ASSIGN_CONFIG: /app/snapshots/snapshot_policy_rules.json
    POLICY_ASSIGN_DRY_RUN: false
    AUTO_SNAPSHOT_DRY_RUN: false
  restart: "no"  # Paused until cross-tenant access available
```

### Enable When Ready

```bash
# Update docker-compose.yml: change restart: "no" to restart: unless-stopped
docker-compose up -d snapshot_worker
```

## Usage

### Modify Policies

Edit `snapshots/snapshot_policy_rules.json` and the scheduler will sync automatically on next run.

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

**Current Limitation**: Service admin lacks cross-tenant roles.

**Workaround**: Snapshots are still created; they're just in the service domain. All metadata tracks the original volume and tenant for recovery purposes.

**Fix**: Wait for tenant admin role assignment (in progress).

### Database Connection Issues

Verify environment variables:
```bash
docker exec pf9_snapshot_worker env | grep PF9_DB
```

Check PostgreSQL:
```bash
psql -h localhost -U pf9 -d pf9_mgmt -c "SELECT COUNT(*) FROM snapshot_records;"
```

## Next Steps

1. **Confirm tenant admin roles assigned** to `erez@ccc.co.il` in each tenant project
2. **Enable snapshot worker**: Update `docker-compose.yml` and restart
3. **Verify snapshots in tenant projects**: Check Horizon or CLI
4. **Monitor compliance**: Use UI dashboard to track snapshot coverage

## References

- [Policy Rules Format](../snapshots/snapshot_policy_rules.json)
- [Snapshot Scheduler](../snapshots/snapshot_scheduler.py)
- [Policy Assignment](../snapshots/p9_snapshot_policy_assign.py)
- [Auto Snapshots](../snapshots/p9_auto_snapshots.py)
- [API Endpoints](../api/snapshot_management.py)
