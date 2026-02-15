# Platform9 Management System - Snapshot Restore Guide

**Version**: 1.2  
**Last Updated**: February 2026  
**Status**: Production Ready (boot-from-volume VMs)  
**Feature Toggle**: Disabled by default — set `RESTORE_ENABLED=true` to activate

---

## Table of Contents

1. [Overview](#overview)
2. [Requirements & Limitations](#requirements--limitations)
3. [Enabling the Feature](#enabling-the-feature)
4. [Environment Variables](#environment-variables)
5. [Restore Modes](#restore-modes)
6. [IP Strategies](#ip-strategies)
7. [RBAC Permissions](#rbac-permissions)
8. [UI Wizard Walkthrough](#ui-wizard-walkthrough)
9. [API Endpoints](#api-endpoints)
10. [Dry-Run Mode](#dry-run-mode)
11. [Volume Cleanup on Failure](#volume-cleanup-on-failure)
12. [Stale Job Recovery](#stale-job-recovery)
13. [Service User Requirement](#service-user-requirement)
14. [Database Schema](#database-schema)
15. [Troubleshooting](#troubleshooting)

---

## Overview

The Snapshot Restore feature allows operators to restore a virtual machine from a Cinder volume snapshot. The system creates a complete restore plan, validates resources, and executes a multi-step workflow:

1. **Plan** — Validate the VM, detect its boot mode, check quotas, and build an ordered action list
2. **Execute** — Create volume from snapshot → create network ports → launch new server → wait for ACTIVE
3. **Track** — Per-step progress stored in `restore_job_steps` table with real-time polling

The restore is fully asynchronous — the API returns immediately after starting execution, and the UI polls for progress updates.

---

## Requirements & Limitations

### Supported
- **Boot-from-volume VMs** — VMs whose root disk is a Cinder volume (the standard for Platform9 environments)
- **Cross-tenant restore** — Restore VMs in any tenant project using the service user mechanism
- **Cloud-init user_data preservation** — The original VM's `user_data` (cloud-init script) is automatically fetched during planning and re-applied to the restored VM, preventing credential or configuration resets on first boot

### Not Yet Supported
- **Boot-from-image VMs** — VMs that boot directly from a Glance image (no Cinder volume). This is planned for a future release.
- **Multiple attached volumes** — Only the boot volume snapshot is restored; additional data volumes must be re-attached manually.
- **Live migration during restore** — The restored VM is created on whatever host Nova schedules it to.

### Prerequisites
- At least one Cinder volume snapshot exists for the target VM's boot volume
- The Platform9 service user must have admin role on the target project (same as snapshot service user)
- Sufficient quota in the target project for: 1 volume, 1 server, N ports (matching original)
- `RESTORE_ENABLED=true` in the environment

---

## Enabling the Feature

### Quick Enable

Add to your `.env` file:
```bash
RESTORE_ENABLED=true
```

Then restart the API container:
```bash
docker-compose restart pf9_api
```

### Full Configuration

```bash
# Required: Enable the restore feature
RESTORE_ENABLED=true

# Optional: Enable dry-run mode (plans are created but never executed)
RESTORE_DRY_RUN=false

# Optional: Clean up volumes created during a failed restore
RESTORE_CLEANUP_VOLUMES=false

# Required for cross-tenant restore (shared with snapshot system):
SNAPSHOT_SERVICE_USER_EMAIL=snapshot-svc@company.com
SNAPSHOT_SERVICE_USER_PASSWORD=<service-user-password>
SNAPSHOT_SERVICE_USER_DOMAIN=default
```

### Via deployment.ps1

When running `deployment.ps1` for the first time (or after deleting `.env`), the interactive wizard will prompt:

```
── Snapshot Restore Configuration ──
Enable Snapshot Restore feature? (true/false) [false]: true
Enable Dry-Run mode? (plans only, no execution) (true/false) [false]: false
Enable Volume Cleanup on failed restores? (true/false) [false]: false
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RESTORE_ENABLED` | `false` | Master feature toggle. When false, all restore endpoints return 404. |
| `RESTORE_DRY_RUN` | `false` | When true, plans are created and saved but execution is skipped. Jobs are marked DRY_RUN. |
| `RESTORE_CLEANUP_VOLUMES` | `false` | When true, volumes created during a failed restore are deleted during rollback. |
| `SNAPSHOT_SERVICE_USER_EMAIL` | *(empty)* | Service user email for cross-tenant operations (shared with snapshot system). |
| `SNAPSHOT_SERVICE_USER_PASSWORD` | *(empty)* | Service user password (shared with snapshot system). |
| `SNAPSHOT_SERVICE_USER_DOMAIN` | `default` | Keystone domain of the service user. |

---

## Restore Modes

### NEW Mode (Default)
Creates a restored VM **alongside** the existing one. The original VM is untouched.

- **Use case**: Recover data, test a restore, or create a point-in-time clone
- **Permissions**: Admin or Superadmin (`restore:write`)
- **VM naming**: Uses `new_vm_name` if provided, otherwise `<original_name>-restored-<timestamp>`
- **No confirmation required**

### REPLACE Mode (Destructive)
**Deletes** the existing VM, then recreates it from the snapshot. The original VM is permanently destroyed.

- **Use case**: Roll back a VM to a known-good state
- **Permissions**: Superadmin only (`restore:admin`)
- **Confirmation required**: The API requires `confirm_destructive` to be set to `DELETE AND RESTORE <vm_name>` (exact match)
- **Rollback**: If the recreate fails after deletion, the job is marked FAILED with details. The original VM cannot be recovered.

> ⚠️ **REPLACE mode is irreversible.** The original VM is deleted before the restore begins. Only use this when you are certain you want to replace the VM.

---

## IP Strategies

When restoring a VM, you can control how network ports and IP addresses are handled:

| Strategy | Behavior | Use Case |
|----------|----------|----------|
| `NEW_IPS` | Creates new ports with DHCP-assigned IPs | Safe default, avoids IP conflicts |
| `TRY_SAME_IPS` | Attempts to reserve the original IPs; falls back to DHCP if unavailable | Best effort to keep same IPs |
| `SAME_IPS_OR_FAIL` | Requires the exact original IPs; fails if any are taken | Strict IP preservation |

**Note**: `TRY_SAME_IPS` and `SAME_IPS_OR_FAIL` require the original networks to still exist. If a network has been deleted, those strategies will fail for ports on that network.

---

## RBAC Permissions

The restore feature uses the standard RBAC system with four permission levels:

| Role | Resource | Action | Capabilities |
|------|----------|--------|-------------|
| **Viewer** | restore | read | View restore jobs and configuration |
| **Operator** | restore | read | View restore jobs and configuration |
| **Admin** | restore | write | Create plans, execute NEW mode restores, cancel jobs |
| **Superadmin** | restore | admin | All above + execute REPLACE mode restores |

### Permission-to-Endpoint Mapping

| Endpoint | Required Permission |
|----------|-------------------|
| `GET /restore/config` | `restore:read` |
| `GET /restore/jobs` | `restore:read` |
| `GET /restore/jobs/{job_id}` | `restore:read` |
| `POST /restore/plan` | `restore:write` |
| `POST /restore/execute` | `restore:write` |
| `POST /restore/cancel/{job_id}` | `restore:write` |
| `GET /restore/snapshots` | `restore:read` |
| `GET /restore/vm/{vm_id}/restore-points` | `restore:read` |

---

## UI Wizard Walkthrough

The Restore tab in the management UI provides a 3-screen guided wizard:

### Screen 1: Select VM
1. Choose the target tenant from the dropdown
2. Select a VM from the list (shows VM name, status, ID)
3. The system loads available snapshots for the selected VM's boot volume

### Screen 2: Configure Restore
1. Select a restore point (snapshot) from the available list
2. Choose restore mode: **NEW** (default) or **REPLACE**
3. Optionally set a custom name for the restored VM (NEW mode only)
4. Choose IP strategy: **NEW_IPS**, **TRY_SAME_IPS**, or **SAME_IPS_OR_FAIL**
5. Click "Generate Plan" to see the detailed action plan

### Screen 3: Execute & Progress
1. Review the generated plan (shows each step and its dependencies)
2. For REPLACE mode: type the confirmation string `DELETE AND RESTORE <vm_name>`
3. Click "Execute" to start the restore
4. Watch real-time progress as each step completes
5. Final status: COMPLETED, FAILED, or DRY_RUN

---

## API Endpoints

### Get Configuration
```bash
GET /restore/config
# Returns: enabled status, dry_run mode, cleanup_volumes setting
```

### List Restore Jobs
```bash
GET /restore/jobs
GET /restore/jobs?status=RUNNING
GET /restore/jobs?vm_id=<uuid>
```

### Get Job Details
```bash
GET /restore/jobs/{job_id}
# Returns: job metadata + all step details with progress
```

### Get Available Snapshots
```bash
GET /restore/snapshots?tenant_name=<name>
# Returns: Cinder snapshots for the tenant, filtered to those with restorable volumes
```

### Get VM Restore Points
```bash
GET /restore/vm/{vm_id}/restore-points?project_id=<id>
# Returns: snapshots of the VM's boot volume, sorted newest first
```

### Create Restore Plan
```bash
POST /restore/plan
Content-Type: application/json

{
  "project_id": "tenant-project-uuid",
  "vm_id": "vm-uuid",
  "restore_point_id": "snapshot-uuid",
  "mode": "NEW",
  "new_vm_name": "my-restored-vm",
  "ip_strategy": "TRY_SAME_IPS"
}
```

### Execute Restore
```bash
POST /restore/execute
Content-Type: application/json

{
  "plan_id": "restore-job-uuid",
  "confirm_destructive": null  # Required for REPLACE: "DELETE AND RESTORE <vm_name>"
}
```

### Cancel Restore
```bash
POST /restore/cancel/{job_id}
Content-Type: application/json

{
  "reason": "Optional cancellation reason"
}
```

---

## Dry-Run Mode

When `RESTORE_DRY_RUN=true`, the system will:
1. Accept plan requests and create full restore plans
2. Save plans to the database with PLANNED status
3. On execute, immediately mark the job as DRY_RUN instead of actually calling OpenStack APIs

This is useful for:
- Testing the restore planning logic without risk
- Validating that all prerequisites are met
- Training operators on the restore workflow

---

## Volume Cleanup on Failure

When `RESTORE_CLEANUP_VOLUMES=true` and a restore job fails:
- Any volumes created during the restore (from snapshot) will be deleted
- This prevents orphaned volumes from consuming quota
- The cleanup is tracked as a rollback step in the job

When `false` (default):
- Failed restore volumes are left in place for manual inspection
- This is safer for debugging failed restores

---

## Stale Job Recovery

On API startup, the system scans for any restore jobs that are still in PENDING or RUNNING status. These are jobs that were interrupted by an API restart or crash.

- PENDING jobs → marked as INTERRUPTED
- RUNNING jobs → marked as INTERRUPTED

Interrupted jobs cannot be resumed. A new restore must be initiated.

---

## Service User Requirement

The restore feature uses the same service user configuration as the snapshot system. The service user must:

1. **Already exist** in Platform9 Keystone (the system does not create users)
2. **Have admin role** on each target project (the system manages role assignments)
3. Be configured via environment variables (`SNAPSHOT_SERVICE_USER_EMAIL`, `SNAPSHOT_SERVICE_USER_PASSWORD`)

See [SNAPSHOT_SERVICE_USER.md](SNAPSHOT_SERVICE_USER.md) for detailed setup instructions.

---

## Database Schema

### restore_jobs Table
| Column | Type | Description |
|--------|------|-------------|
| id | UUID (PK) | Unique job identifier |
| tenant_id | VARCHAR(255) | Target project/tenant ID |
| vm_id | VARCHAR(255) | Original VM ID |
| snapshot_id | VARCHAR(255) | Source Cinder snapshot ID |
| mode | VARCHAR(20) | NEW or REPLACE |
| status | VARCHAR(20) | PLANNED, PENDING, RUNNING, COMPLETED, FAILED, CANCELLED, INTERRUPTED, DRY_RUN |
| plan_json | JSONB | Full restore plan with steps |
| result_json | JSONB | Execution results and created resource IDs |
| requested_by | VARCHAR(255) | Username who initiated the restore |
| created_at | TIMESTAMPTZ | Job creation time |
| started_at | TIMESTAMPTZ | Execution start time |
| completed_at | TIMESTAMPTZ | Execution end time |
| last_heartbeat | TIMESTAMPTZ | Last progress update time |

### restore_job_steps Table
| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL (PK) | Step sequence ID |
| job_id | UUID (FK) | Parent restore job |
| step_order | INT | Execution order |
| action | VARCHAR(50) | Step type (create_volume, create_port, etc.) |
| status | VARCHAR(20) | PENDING, RUNNING, COMPLETED, FAILED, SKIPPED |
| detail_json | JSONB | Step-specific parameters and results |
| started_at | TIMESTAMPTZ | Step start time |
| completed_at | TIMESTAMPTZ | Step end time |

---

## Troubleshooting

### Feature Not Available
- **Symptom**: Restore tab doesn't appear in UI, or endpoints return 404
- **Fix**: Set `RESTORE_ENABLED=true` in `.env` and restart `pf9_api` container

### "Permission denied" Errors
- **Symptom**: 403 responses on restore endpoints
- **Fix**: Ensure user has appropriate role. Plan/execute requires admin+. REPLACE requires superadmin.

### "Quota exceeded" During Restore
- **Symptom**: Restore fails at volume creation step
- **Fix**: Free up quota in the target project (volumes, instances, cores, RAM) before retrying

### Cross-Tenant Restore Fails
- **Symptom**: 401/403 from OpenStack APIs during restore execution
- **Fix**: Ensure `SNAPSHOT_SERVICE_USER_EMAIL` and `SNAPSHOT_SERVICE_USER_PASSWORD` are set. Verify the service user has admin role on the target project.

### Stale Jobs After API Restart
- **Symptom**: Old jobs show INTERRUPTED status
- **Explanation**: This is expected — jobs that were in progress when the API restarted are automatically marked INTERRUPTED. Start a new restore.

### REPLACE Mode Confirmation
- **Symptom**: 400 error "Destructive confirmation required"
- **Fix**: Set `confirm_destructive` to exactly `DELETE AND RESTORE <vm_name>` (case-sensitive, use the original VM name)

### Volumes Left After Failed Restore
- **Symptom**: Orphaned volumes with names like `restored-<name>-<timestamp>`
- **Fix**: Either set `RESTORE_CLEANUP_VOLUMES=true` for automatic cleanup, or manually delete orphaned volumes via the Platform9 UI

---

**Related Documentation**:
- [API Reference](API_REFERENCE.md) — Complete API endpoint documentation
- [Security Guide](SECURITY.md) — RBAC and permission model
- [Snapshot Service User](SNAPSHOT_SERVICE_USER.md) — Service user setup
- [Deployment Guide](DEPLOYMENT_GUIDE.md) — Environment configuration
- [Admin Guide](ADMIN_GUIDE.md) — Day-to-day administration
