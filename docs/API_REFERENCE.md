# Platform9 Management API Reference

## Base URL
```
http://localhost:8000
```

## Authentication

All authenticated endpoints require a Bearer token in the Authorization header:
```
Authorization: Bearer <your_jwt_token>
```

### Get Token
**POST** `/auth/login`

Request:
```json
{
  "username": "admin",
  "password": "your-password"
}
```

Response:
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer",
  "expires_in": 28800,
  "expires_at": "2026-02-08T17:00:00Z",
  "user": {
    "username": "admin",
    "role": "superadmin",
    "is_active": true
  }
}
```

---

## Dashboard Endpoints

### Health Summary
**GET** `/dashboard/health-summary`

Returns system-wide operational metrics.

Response:
```json
{
  "timestamp": "2026-02-08T09:00:00Z",
  "total_tenants": 28,
  "total_vms": 145,
  "vms_running": 132,
  "total_volumes": 267,
  "total_networks": 45,
  "avg_cpu_utilization": 42.5,
  "avg_memory_utilization": 58.3,
  "alerts": {
    "critical": 2,
    "warning": 5,
    "info": 12
  },
  "metrics_last_update": "2026-02-08T08:55:00Z"
}
```

### Snapshot SLA Compliance
**GET** `/dashboard/snapshot-sla-compliance`  
Query Parameters:
- `days` (optional, default: 2) - SLA compliance window in days

Returns snapshot compliance status by tenant.

Response:
```json
{
  "overall_compliance": 87.5,
  "tenants": [
    {
      "tenant_id": "abc123",
      "tenant_name": "Production",
      "domain_name": "Default",
      "total_volumes": 50,
      "compliant": 45,
      "warning": 3,
      "critical": 2,
      "compliance_percentage": 90.0,
      "warnings": [
        {
          "volume_id": "vol-123",
          "volume_name": "db-volume-01",
          "policy": "daily_5",
          "last_snapshot": "2026-02-06T00:00:00Z",
          "message": "No snapshot in last 2 days"
        }
      ]
    }
  ]
}
```

### Top Hosts Utilization
**GET** `/dashboard/top-hosts-utilization`  
Query Parameters:
- `limit` (optional, default: 10, max: 20) - Number of hosts to return
- `sort` (optional, default: "cpu") - Sort by "cpu" or "memory"

Returns top hosts by resource utilization.

Response:
```json
{
  "hosts": [
    {
      "hostname": "compute-01.local",
      "cpu_percent": 85.2,
      "memory_percent": 72.4,
      "vm_count": 12,
      "status": "critical"
    }
  ],
  "total_hosts": 5,
  "timestamp": "2026-02-08T09:00:00Z"
}
```

### Recent Changes
**GET** `/dashboard/recent-changes`  
Query Parameters:
- `hours` (optional, default: 24) - Lookback window in hours
- `limit` (optional, default: 20) - Maximum changes to return

Returns recent infrastructure changes.

Response:
```json
{
  "changes": [
    {
      "timestamp": "2026-02-08T08:30:00Z",
      "type": "vm_created",
      "resource_id": "vm-456",
      "resource_name": "web-server-03",
      "project_name": "Production",
      "user": "admin",
      "details": "New VM created with flavor m1.large"
    }
  ],
  "total_changes": 18,
  "period_hours": 24
}
```

### Coverage Risks
**GET** `/dashboard/coverage-risks`

Returns volumes without snapshot protection.

Response:
```json
{
  "total_at_risk": 15,
  "total_volumes": 267,
  "risk_percentage": 5.6,
  "volumes": [
    {
      "volume_id": "vol-789",
      "volume_name": "temp-storage",
      "size_gb": 100,
      "tenant_name": "Development",
      "risk_score": 8,
      "recommendation": "Enable auto-snapshot with daily_5 policy"
    }
  ]
}
```

### Capacity Pressure
**GET** `/dashboard/capacity-pressure`

Returns capacity warnings for storage and compute.

Response:
```json
{
  "storage_pressure": [
    {
      "pool_name": "infinidat-pool2",
      "used_percent": 82.5,
      "available_gb": 2048,
      "status": "warning",
      "forecast_full": "45 days"
    }
  ],
  "compute_pressure": [
    {
      "hostname": "compute-02",
      "cpu_used_percent": 88.0,
      "memory_used_percent": 91.2,
      "status": "critical"
    }
  ]
}
```

### VM Hotspots
**GET** `/dashboard/vm-hotspots`  
Query Parameters:
- `sort` (optional, default: "cpu") - Sort by "cpu", "memory", or "storage"
- `limit` (optional, default: 10) - Number of VMs to return

Returns top resource-consuming VMs.

Response:
```json
{
  "hotspots": [
    {
      "vm_id": "vm-123",
      "vm_name": "database-master",
      "tenant_name": "Production",
      "cpu_percent": 95.2,
      "memory_percent": 88.7,
      "storage_gb": 500,
      "status": "critical"
    }
  ],
  "sort_by": "cpu",
  "total_vms": 145
}
```

### Tenant Risk Scores
**GET** `/dashboard/tenant-risk-scores`

Returns multi-factor risk assessment per tenant.

Response:
```json
{
  "tenants": [
    {
      "tenant_id": "abc123",
      "tenant_name": "Production",
      "risk_score": 65,
      "risk_level": "medium",
      "factors": {
        "overutilization": 70,
        "missing_snapshots": 40,
        "cost_trend": 80
      },
      "recommendations": [
        "Review high CPU utilization on 3 VMs",
        "Enable snapshots on 5 volumes"
      ]
    }
  ]
}
```

### Compliance Drift
**GET** `/dashboard/compliance-drift`  
Query Parameters:
- `days` (optional, default: 7) - Trending period

Returns policy compliance trending over time.

Response:
```json
{
  "period_days": 7,
  "drift_events": [
    {
      "date": "2026-02-07",
      "compliance_percent": 85.0,
      "violations": 12,
      "trend": "improving"
    }
  ],
  "current_compliance": 87.5,
  "trend": "improving"
}
```

### Capacity Trends
**GET** `/dashboard/capacity-trends`  
Query Parameters:
- `days` (optional, default: 7) - Historical period

Returns capacity utilization trending.

Response:
```json
{
  "storage_trend": [
    {
      "date": "2026-02-08",
      "used_percent": 68.5,
      "available_gb": 15360
    }
  ],
  "cpu_trend": [
    {
      "date": "2026-02-08",
      "avg_utilization": 42.5
    }
  ],
  "forecast": {
    "storage_full_date": "2026-08-15",
    "cpu_saturation_date": null
  }
}
```

### Trendlines
**GET** `/dashboard/trendlines`  
Query Parameters:
- `period` (optional, default: 7) - Days to analyze (7, 30, or 90)

Returns infrastructure growth patterns.

Response:
```json
{
  "period_days": 7,
  "metrics": {
    "vms": {
      "current": 145,
      "start": 138,
      "change": 7,
      "change_percent": 5.1,
      "velocity_per_day": 1.0
    },
    "volumes": {
      "current": 267,
      "start": 255,
      "change": 12,
      "change_percent": 4.7,
      "velocity_per_day": 1.7
    }
  },
  "forecast_30_days": {
    "vms": 175,
    "volumes": 318
  }
}
```

---

## Infrastructure Endpoints

### Domains
**GET** `/domains`  
Returns all OpenStack domains with project counts.

### Projects/Tenants
**GET** `/projects`  
**GET** `/tenants` (alias)  
Returns all projects/tenants with resource counts.

Query Parameters:
- `domain_id` (optional) - Filter by domain

### Servers (VMs)
**GET** `/servers`  
Returns all virtual machines with detailed status, resource allocation, and host utilization.

Query Parameters:
- `domain_name` (optional) - Filter by domain
- `tenant_id` (optional) - Filter by project/tenant
- `status` (optional) - Filter by status (ACTIVE, SHUTOFF, etc.)
- `page` / `page_size` - Pagination (default 1 / 50)
- `sort_by` / `sort_dir` - Sort column and direction

Response fields per server:
| Field | Type | Description |
|-------|------|-------------|
| `vm_id` | string | Server UUID |
| `vm_name` | string | Server display name |
| `domain_name` | string | Parent domain |
| `tenant_name` | string | Parent project/tenant |
| `status` | string | VM status (ACTIVE, SHUTOFF, etc.) |
| `flavor_name` | string | Flavor template name |
| `vcpus` | int | Allocated vCPUs (from flavor) |
| `ram_mb` | int | Allocated RAM in MB (from flavor) |
| `disk_gb` | int | **Actual disk size** — uses flavor disk, or sum of attached volume sizes for boot-from-volume VMs |
| `ips` | string | Comma-separated fixed and floating IPs |
| `image_name` | string | Boot image name |
| `hypervisor_hostname` | string | Physical host running VM |
| `host_vcpus_total` | int | Total vCPUs on the host |
| `host_vcpus_used` | int | vCPUs allocated across all VMs on the host |
| `host_ram_total_mb` | int | Total RAM (MB) on the host |
| `host_ram_used_mb` | int | RAM allocated across all VMs on the host |
| `host_disk_total_gb` | int | Total local disk (GB) on the host |
| `host_disk_used_gb` | int | Local disk used on the host |
| `host_running_vms` | int | Number of VMs running on the host |

### Volumes
**GET** `/volumes`  
Returns all block storage volumes.

Query Parameters:
- `project_id` (optional) - Filter by project
- `status` (optional) - Filter by status

**GET** `/volumes/{volume_id}/metadata`  
Returns snapshot policy metadata for a specific volume.

**GET** `/volumes/metadata/bulk`  
Returns snapshot metadata for all volumes in bulk.

### Snapshots
**GET** `/snapshots`  
Returns all volume snapshots with compliance status.

Query Parameters:
- `project_id` (optional) - Filter by project
- `volume_id` (optional) - Filter by volume

**GET** `/snapshot/compliance`  
Returns snapshot compliance report with SLA analysis.

Query Parameters:
- `days` (optional, default: 2) - SLA window
- `tenant_id` (optional) - Filter by tenant
- `project_id` (optional) - Filter by project

### Networks
**GET** `/networks`  
Returns all virtual networks.

**POST** `/admin/networks` (Admin only)  
Create a new network.

**DELETE** `/admin/networks/{network_id}` (Admin only)  
Delete a network.

### Subnets
**GET** `/subnets`  
Returns all subnets with CIDR and gateway information.

### Ports
**GET** `/ports`  
Returns all network ports with device attachments.

### Floating IPs
**GET** `/floatingips`  
Returns all floating IP addresses.

### Security Groups
**GET** `/security-groups`  
Returns all security groups with attached VM/network counts and rule counts.

Query Parameters:
- `page` / `page_size` — Pagination (default 1/50)
- `sort_by` / `sort_dir` — Sort field and direction
- `domain_name` — Filter by domain
- `tenant_name` — Filter by tenant
- `name` — Filter by security group name (partial match)

**GET** `/security-groups/{sg_id}`  
Returns detailed info for a single security group including:
- All rules (ingress and egress)
- Attached VMs (via port security_groups JSONB)
- Attached networks

**GET** `/security-group-rules`  
Returns all security group rules with pagination and filtering.

**POST** `/admin/security-groups` (Admin only)  
Create a new security group.
```json
{
  "name": "web-servers",
  "description": "Allow HTTP/HTTPS traffic",
  "project_id": "optional-project-uuid"
}
```

**DELETE** `/admin/security-groups/{sg_id}` (Admin only)  
Delete a security group and all its rules.

**POST** `/admin/security-group-rules` (Admin only)  
Create a security group rule.
```json
{
  "security_group_id": "sg-uuid",
  "direction": "ingress",
  "protocol": "tcp",
  "port_range_min": 443,
  "port_range_max": 443,
  "remote_ip_prefix": "0.0.0.0/0",
  "ethertype": "IPv4",
  "description": "Allow HTTPS"
}
```

**DELETE** `/admin/security-group-rules/{rule_id}` (Admin only)  
Delete a security group rule.

### Flavors
**GET** `/flavors`  
Returns all VM flavors (sizes).

**POST** `/admin/flavors` (Admin only)  
Create a new flavor.

**DELETE** `/admin/flavors/{flavor_id}` (Admin only)  
Delete a flavor.

### Images
**GET** `/images`  
Returns all VM images.

### Hypervisors
**GET** `/hypervisors`  
Returns all compute nodes with resource stats.

---

## User Management Endpoints

### Users
**GET** `/users`  
Returns all users across all domains.

Query Parameters:
- `domain_id` (optional) - Filter by domain
- `enabled` (optional) - Filter by account status

**GET** `/users/{user_id}`  
Returns detailed information for a specific user.

### Roles
**GET** `/roles`  
Returns all roles in the system.

**GET** `/roles/{role_id}`  
Returns detailed information for a specific role.

### Role Assignments
**GET** `/role-assignments`  
Returns all role assignments.

Query Parameters:
- `user_id` (optional) - Filter by user
- `project_id` (optional) - Filter by project
- `role_id` (optional) - Filter by role

### User Activity
**GET** `/user-activity-summary`  
Returns activity summary for all users.

**POST** `/admin/user-access-log` (Admin only)  
Logs user access events for monitoring.

---

## History & Audit Endpoints

### Recent Changes
**GET** `/history/recent-changes`  
Returns recent resource changes from the `v_comprehensive_changes` view (includes all resource types and deletions).

Query Parameters:
- `hours` (optional, default: 24, max: 168) - Lookback period
- `limit` (optional, default: 100, max: 1000) - Maximum results

### Most Changed Resources
**GET** `/history/most-changed`  
Returns resources with the highest number of recorded changes.

Query Parameters:
- `hours` (optional, default: 24) - Lookback period
- `limit` (optional, default: 20) - Maximum results

### Changes by Timeframe
**GET** `/history/by-timeframe`  
Returns changes grouped by time period for trend analysis.

### Resource History
**GET** `/history/resource/{resource_type}/{resource_id}`  
Returns complete change history for a specific resource.

Valid `resource_type` values: `server`, `domain`, `project`, `flavor`, `image`, `hypervisor`, `network`, `volume`, `floating_ip`, `snapshot`, `port`, `subnet`, `router`, `user`, `role`, **`deletion`**

Query Parameters:
- `limit` (optional, default: 100, max: 1000) - Maximum history entries

> **Note**: `deletion` queries the `deletions_history` table directly and returns the deletion event with original resource type, reason, last-seen timestamp, and raw JSON state snapshot.

### Compare History Entries
**GET** `/history/compare/{resource_type}/{resource_id}`  
Compares two history entries to show field-level differences.

Query Parameters:
- `current_hash` (required) - Current change hash
- `previous_hash` (required) - Previous change hash

> **Note**: Not available for `deletion` resource type (returns info message).

### Change Details
**GET** `/history/details/{resource_type}/{resource_id}`  
Returns detailed change information including change sequence numbering and key field extraction.

### Resource Timeline
**GET** `/audit/resource-timeline/{resource_type}`  
Returns timeline of all changes for a resource type.

Query Parameters:
- `days` (optional, default: 30) - Historical period

### Compliance Report
**GET** `/audit/compliance-report`  
Returns compliance status report.

Query Parameters:
- `start_date` (optional) - Report start date
- `end_date` (optional) - Report end date

---

## Snapshot Policy Management

### Policy Sets
**GET** `/snapshot-policies`  
Returns all snapshot policy sets.

**POST** `/snapshot-policies` (Admin only)  
Create a new policy set.

**PUT** `/snapshot-policies/{policy_id}` (Admin only)  
Update an existing policy set.

**DELETE** `/snapshot-policies/{policy_id}` (Admin only)  
Delete a policy set.

### Volume Assignments
**GET** `/snapshot-assignments`  
Returns snapshot policy assignments.

Query Parameters:
- `volume_id` (optional) - Filter by volume
- `policy_set_id` (optional) - Filter by policy set

**POST** `/snapshot-assignments` (Admin only)  
Assign a policy to volumes.

**DELETE** `/snapshot-assignments/{assignment_id}` (Admin only)  
Remove a policy assignment.

### Snapshot Runs
**GET** `/snapshot-runs`  
Returns history of automated snapshot runs.

Query Parameters:
- `limit` (optional, default: 50) - Results limit
- `status` (optional) - Filter by status

### Snapshot Run Progress (v1.26.0)
**GET** `/snapshot/runs/{run_id}/progress` (Authenticated, `snapshot_runs:read`)  
Returns live progress for a specific snapshot run including batch details and quota-blocked volumes.

**Response**:
```json
{
  "run": {
    "id": 42,
    "status": "running",
    "total_volumes": 85,
    "snapshots_created": 40,
    "total_batches": 5,
    "completed_batches": 2,
    "current_batch": 3,
    "quota_blocked": 3,
    "progress_pct": 47.1,
    "estimated_finish_at": "2026-02-24T14:30:00+00:00"
  },
  "batches": [
    {
      "batch_number": 1,
      "tenant_names": ["prod-east", "prod-west"],
      "total_volumes": 20,
      "status": "completed"
    }
  ],
  "quota_blocks": [
    {
      "volume_name": "db-data-01",
      "tenant_name": "staging",
      "quota_limit_gb": 500,
      "quota_used_gb": 480,
      "quota_needed_gb": 50,
      "block_reason": "Insufficient storage quota"
    }
  ],
  "is_active": true
}
```

### Active Run Progress (v1.26.0)
**GET** `/snapshot/runs/active/progress` (Authenticated, `snapshot_runs:read`)  
Returns progress for the currently-running snapshot run, if any. Designed for live polling by the UI.

**Response** (active run):
```json
{
  "active": true,
  "run": { "id": 42, "status": "running", "progress_pct": 65.0, "..." : "..." },
  "batches": [ { "batch_number": 1, "status": "completed", "..." : "..." } ]
}
```

**Response** (no active run):
```json
{ "active": false, "run": null, "batches": [] }
```

---

## Monitoring Endpoints

### API Health
**GET** `/health`  
Returns API health status (public endpoint).

Response:
```json
{
  "status": "ok",
  "service": "pf9-mgmt-api",
  "timestamp": "2026-02-08T09:00:00Z"
}
```

### Metrics
**GET** `/metrics` (Public)  
**GET** `/api/metrics` (Authenticated)  
Returns performance metrics.

Response:
```json
{
  "uptime_seconds": 86400,
  "request_count": 15234,
  "avg_response_time_ms": 45.2,
  "error_rate": 0.02,
  "active_sessions": 12
}
```

### Logs
**GET** `/api/logs` (Authenticated, Admin only)  
Returns system logs.

Query Parameters:
- `limit` (optional, default: 100) - Number of log entries
- `level` (optional) - Filter by level (DEBUG, INFO, WARNING, ERROR)
- `source` (optional) - Filter by source (pf9_api, pf9_monitoring)
- `log_file` (optional) - Specific log file or "all"

---

## On-Demand Snapshot Pipeline

### Trigger Pipeline
**POST** `/snapshot/run-now` (Admin only, `snapshots:admin`)  
Triggers the full snapshot pipeline on demand: policy assignment → inventory sync → auto snapshots → inventory sync. Returns immediately with a job ID.

**Response** (202 Accepted):
```json
{
  "job_id": "abc-123",
  "status": "pending",
  "message": "Snapshot pipeline queued. The worker will pick it up within 10 seconds. Poll /snapshot/run-now/status for progress."
}
```

**Error** (409 Conflict — pipeline already pending or running):
```json
{ "detail": "An on-demand snapshot pipeline is already pending or running." }
```

### Get Pipeline Status
**GET** `/snapshot/run-now/status` (Authenticated, `snapshots:read`)  
Returns the status of the most recent on-demand snapshot pipeline run.

**Response**:
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

Step statuses: `pending`, `running`, `completed`, `failed`  
Job statuses: `idle`, `pending`, `running`, `completed`, `failed`  

> **Architecture note**: The API queues the pipeline by writing a `pending` row to the `snapshot_on_demand_runs` database table. The `snapshot_worker` container picks it up within 10 seconds and executes the full pipeline, updating step progress in real time.

---

## Snapshot Restore Endpoints

> **Feature Toggle**: These endpoints require `RESTORE_ENABLED=true`. When disabled, all restore endpoints return 404.  
> **RBAC**: All endpoints require authentication. See permission requirements per endpoint below.  
> **Full Guide**: See [RESTORE_GUIDE.md](RESTORE_GUIDE.md) for detailed feature documentation.

### Get Restore Configuration
**GET** `/restore/config` (Authenticated, `restore:read`)  
Returns current restore feature configuration.

Response:
```json
{
  "enabled": true,
  "dry_run": false,
  "cleanup_volumes": false
}
```

### List Available Snapshots
**GET** `/restore/snapshots` (Authenticated, `restore:read`)  
Returns Cinder snapshots available for restore.

Query Parameters:
- `tenant_name` (required) - Tenant name to fetch snapshots for

### Get VM Restore Points
**GET** `/restore/vm/{vm_id}/restore-points` (Authenticated, `restore:read`)  
Returns snapshots of a specific VM's boot volume, sorted newest first.

Query Parameters:
- `project_id` (required) - Project ID the VM belongs to

### Create Restore Plan
**POST** `/restore/plan` (Authenticated, `restore:write`)  
Validates resources and creates a restore plan without executing it.

Request Body:
```json
{
  "project_id": "tenant-project-uuid",
  "vm_id": "vm-uuid",
  "restore_point_id": "snapshot-uuid",
  "mode": "NEW",
  "new_vm_name": "my-restored-vm",
  "ip_strategy": "TRY_SAME_IPS"
}
```

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `project_id` | Yes | — | Target project UUID |
| `vm_id` | Yes | — | Original VM UUID |
| `restore_point_id` | Yes | — | Cinder snapshot UUID |
| `mode` | No | `NEW` | `NEW` (side-by-side) or `REPLACE` (destructive) |
| `new_vm_name` | No | auto-generated | Name for the restored VM (NEW mode only) |
| `ip_strategy` | No | `NEW_IPS` | `NEW_IPS`, `TRY_SAME_IPS`, `SAME_IPS_OR_FAIL`, or `MANUAL_IP` |
| `manual_ips` | No | — | Dict mapping network IDs to desired IPs (only used with `MANUAL_IP` strategy) |

Response: Restore job object with status `PLANNED` and full `plan_json`.

### List Available IPs on a Network
**GET** `/restore/networks/{network_id}/available-ips` (Authenticated, `restore:read`)  
Lists available (unused) IPs on each subnet of the given network. Queries Neutron for subnet CIDRs and existing ports, then computes free IPs (up to 200 per subnet).

Response:
```json
{
  "network_id": "network-uuid",
  "subnets": [
    {
      "subnet_id": "subnet-uuid",
      "subnet_name": "my-subnet",
      "cidr": "10.0.0.0/24",
      "gateway_ip": "10.0.0.1",
      "available_ips": ["10.0.0.50", "10.0.0.51", "..."],
      "available_count": 200
    }
  ]
}
```

### Execute Restore Plan
**POST** `/restore/execute` (Authenticated, `restore:write`)  
Starts execution of a previously-created restore plan.

Request Body:
```json
{
  "plan_id": "restore-job-uuid",
  "confirm_destructive": null
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `plan_id` | Yes | UUID of a restore job in PLANNED status |
| `confirm_destructive` | REPLACE only | Must be exactly `DELETE AND RESTORE <vm_name>` |

Response: Restore job object with status `PENDING` (execution starts asynchronously).

### List Restore Jobs
**GET** `/restore/jobs` (Authenticated, `restore:read`)  
Returns all restore jobs, sorted by creation time (newest first).

Query Parameters:
- `status` (optional) - Filter by job status
- `vm_id` (optional) - Filter by original VM ID

### Get Restore Job Details
**GET** `/restore/jobs/{job_id}` (Authenticated, `restore:read`)  
Returns detailed job information including all step statuses.

Path Parameters:
- `job_id` (required) - UUID of the restore job

### Cancel Restore Job
**POST** `/restore/cancel/{job_id}` (Authenticated, `restore:write`)  
Requests cancellation of a running or pending restore job.

Request Body:
```json
{
  "reason": "Optional cancellation reason"
}
```

### Cleanup Failed Restore Job
**POST** `/restore/jobs/{job_id}/cleanup` (Authenticated, `restore:admin`)  
Clean up orphaned OpenStack resources (ports, volumes) from a failed/canceled/interrupted restore job.

Request Body:
```json
{
  "delete_volume": false  // true to also delete the orphaned volume
}
```

Response:
```json
{
  "job_id": "uuid",
  "cleaned": {
    "ports": ["port-id-1"],
    "volume": "vol-id (preserved — use delete_volume=true to remove)",
    "server": null,
    "errors": []
  },
  "message": "Cleanup completed"
}
```

### Retry Failed Restore Job
**POST** `/restore/jobs/{job_id}/retry` (Authenticated, `restore:admin`)  
Retry a failed restore job from the failed step. Reuses already-created resources (volumes, ports). Optionally override IP strategy.

Request Body:
```json
{
  "confirm_destructive": "DELETE AND RESTORE <vm_name>",  // required for REPLACE mode
  "ip_strategy_override": "TRY_SAME_IPS"  // optional: NEW_IPS, TRY_SAME_IPS, SAME_IPS_OR_FAIL
}
```

Response:
```json
{
  "job_id": "new-retry-job-uuid",
  "original_job_id": "original-failed-job-uuid",
  "status": "PENDING",
  "resumed_from_step": "CREATE_PORTS",
  "reused_resources": {
    "volume_id": "vol-id"
  },
  "ip_strategy": "TRY_SAME_IPS",
  "message": "Retry execution started. Poll /restore/jobs/{job_id} for progress."
}
```

### Cleanup Storage from Completed Restore
**POST** `/restore/jobs/{job_id}/cleanup-storage` (Authenticated, `restore:admin`)  
Delete orphaned storage left behind by a completed REPLACE-mode restore.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `delete_old_volume` | bool | `true` | Delete the original VM's orphaned root volume |
| `delete_source_snapshot` | bool | `false` | Delete the source Cinder snapshot used for the restore |

Safety checks:
- Only works on COMPLETED jobs
- Old volume deletion only applies to REPLACE mode
- Won't delete volumes that are still attached or in-use
- Won't delete snapshots that aren't in "available" status

```json
{
  "job_id": "abc123",
  "result": {
    "deleted_volumes": ["vol-uuid"],
    "deleted_snapshots": [],
    "errors": [],
    "skipped": []
  },
  "message": "Storage cleanup completed"
}
```

---

## Drift Detection Endpoints

> **Version**: v1.9.0  
> **RBAC**: `drift:read` for all authenticated roles; `drift:write` (acknowledge, toggle rules) for Operator and above.  
> **Domain/Tenant Filtering**: All event endpoints respect the caller's domain and tenant scope.

### Get Drift Summary
**GET** `/drift/summary` (Authenticated, `drift:read`)  
Returns an aggregate overview of drift events grouped by severity, resource type, and acknowledgement status.

Query Parameters:
- `domain_name` (optional) - Filter by domain
- `tenant_name` (optional) - Filter by tenant

Response:
```json
{
  "total_events": 42,
  "unacknowledged": 28,
  "by_severity": {
    "critical": 5,
    "warning": 18,
    "info": 19
  },
  "by_resource_type": {
    "server": 12,
    "volume": 9,
    "network": 6,
    "floating_ip": 5,
    "port": 4,
    "subnet": 3,
    "security_group": 2,
    "snapshot": 1
  },
  "last_detected_at": "2026-02-16T08:30:00Z"
}
```

### List Drift Events
**GET** `/drift/events` (Authenticated, `drift:read`)  
Returns drift events with filtering, sorting, and pagination.

Query Parameters:
- `page` / `page_size` (optional, default: 1 / 50) - Pagination
- `sort_by` / `sort_dir` (optional) - Sort field and direction
- `resource_type` (optional) - Filter by resource type (server, volume, network, subnet, port, floating_ip, security_group, snapshot)
- `severity` (optional) - Filter by severity (critical, warning, info)
- `acknowledged` (optional) - Filter by acknowledgement status (true/false)
- `domain_name` (optional) - Filter by domain
- `tenant_name` (optional) - Filter by tenant
- `search` (optional) - Free-text search across resource name/ID

Response:
```json
{
  "total": 42,
  "page": 1,
  "page_size": 50,
  "events": [
    {
      "id": 1,
      "resource_type": "server",
      "resource_id": "vm-abc123",
      "resource_name": "web-server-01",
      "field_name": "status",
      "old_value": "ACTIVE",
      "new_value": "SHUTOFF",
      "severity": "critical",
      "rule_name": "Server Status Change",
      "detected_at": "2026-02-16T08:30:00Z",
      "acknowledged": false,
      "acknowledged_by": null,
      "acknowledged_at": null,
      "domain_name": "Default",
      "tenant_name": "Production"
    }
  ]
}
```

### Get Drift Event Detail
**GET** `/drift/events/{id}` (Authenticated, `drift:read`)  
Returns full detail for a single drift event including rule metadata.

Path Parameters:
- `id` (required) - Drift event ID

Response:
```json
{
  "id": 1,
  "resource_type": "server",
  "resource_id": "vm-abc123",
  "resource_name": "web-server-01",
  "field_name": "status",
  "old_value": "ACTIVE",
  "new_value": "SHUTOFF",
  "severity": "critical",
  "rule_id": 3,
  "rule_name": "Server Status Change",
  "rule_description": "Detects when a server's power status changes unexpectedly",
  "detected_at": "2026-02-16T08:30:00Z",
  "acknowledged": false,
  "acknowledged_by": null,
  "acknowledged_at": null,
  "domain_name": "Default",
  "tenant_name": "Production"
}
```

### Acknowledge Drift Event
**PUT** `/drift/events/{id}/acknowledge` (Authenticated, `drift:write`)  
Acknowledges a single drift event. Records the acknowledging user and timestamp.

Path Parameters:
- `id` (required) - Drift event ID

Response:
```json
{
  "id": 1,
  "acknowledged": true,
  "acknowledged_by": "operator@company.com",
  "acknowledged_at": "2026-02-16T09:00:00Z"
}
```

### Bulk Acknowledge Drift Events
**PUT** `/drift/events/bulk-acknowledge` (Authenticated, `drift:write`)  
Acknowledges multiple drift events in a single operation.

Request Body:
```json
{
  "event_ids": [1, 2, 5, 12, 15]
}
```

Response:
```json
{
  "acknowledged_count": 5,
  "acknowledged_by": "operator@company.com",
  "acknowledged_at": "2026-02-16T09:00:00Z"
}
```

### List Drift Rules
**GET** `/drift/rules` (Authenticated, `drift:read`)  
Returns all 24 built-in drift detection rules with their current enabled/disabled status.

Response:
```json
{
  "rules": [
    {
      "id": 1,
      "resource_type": "server",
      "field_name": "flavor_id",
      "rule_name": "Server Flavor Change",
      "description": "Detects when a server's flavor (size) is changed",
      "severity": "warning",
      "enabled": true
    },
    {
      "id": 2,
      "resource_type": "server",
      "field_name": "status",
      "rule_name": "Server Status Change",
      "description": "Detects when a server's power status changes unexpectedly",
      "severity": "critical",
      "enabled": true
    },
    {
      "id": 3,
      "resource_type": "server",
      "field_name": "vm_state",
      "rule_name": "Server VM State Change",
      "description": "Detects changes to the underlying VM state",
      "severity": "warning",
      "enabled": true
    },
    {
      "id": 4,
      "resource_type": "server",
      "field_name": "hypervisor_hostname",
      "rule_name": "Server Migration Detected",
      "description": "Detects when a server is live-migrated to a different host",
      "severity": "info",
      "enabled": true
    }
  ],
  "total": 24
}
```

**Built-in Rules by Resource Type**:

| Resource Type | Monitored Fields | Rule Count |
|---------------|-----------------|------------|
| server | flavor_id, status, vm_state, hypervisor_hostname | 4 |
| volume | status, size, volume_type, server_id | 4 |
| network | admin_state_up, shared | 2 |
| subnet | gateway_ip, cidr, enable_dhcp | 3 |
| port | device_id, mac_address, status | 3 |
| floating_ip | port_id, router_id, status | 3 |
| security_group | description | 1 |
| snapshot | status, size | 2 |
| **Total** | | **24** |

### Update Drift Rule
**PUT** `/drift/rules/{rule_id}` (Authenticated, `drift:write`)  
Enables or disables a specific drift detection rule.

Path Parameters:
- `rule_id` (required) - Rule ID

Request Body:
```json
{
  "enabled": false
}
```

Response:
```json
{
  "id": 4,
  "rule_name": "Server Migration Detected",
  "enabled": false,
  "updated_by": "admin@company.com",
  "updated_at": "2026-02-16T09:05:00Z"
}
```

---

## Tenant Health Endpoints

> **Version**: v1.10.0
> **RBAC**: `tenant_health:read` for all authenticated roles; `tenant_health:admin` for Admin and Superadmin.
> **Database**: Powered by the `v_tenant_health` SQL view which aggregates per-project health metrics from all resource tables.

### Health Score Formula
Each tenant starts with a score of **100**. Deductions are applied for:
- **Error VMs/Volumes/Snapshots**: Resources in error state reduce the score
- **Low Compliance**: Snapshot compliance below threshold
- **Critical Drift**: Recent critical or warning drift events

### Tenant Health Overview
**GET** `/tenant-health/overview` (Authenticated, `tenant_health:read`)
Returns all tenants with health scores and summary statistics.

Query Parameters:
- `domain_id` (optional) - Filter by domain
- `sort_by` (optional, default: `health_score`) - Sort field: `health_score`, `project_name`, `domain_name`, `total_servers`, `total_volumes`, `total_networks`, `total_drift_events`, `compliance_pct`
- `sort_dir` (optional, default: `desc`) - Sort direction: `asc` or `desc`
- `search` (optional) - Free-text search across tenant/domain name

Response:
```json
{
  "summary": {
    "total_tenants": 28,
    "healthy": 20,
    "warning": 5,
    "critical": 3,
    "avg_health_score": 82.4
  },
  "tenants": [
    {
      "project_id": "abc-123",
      "project_name": "Production",
      "domain_id": "default",
      "domain_name": "Default",
      "health_score": 95,
      "health_status": "healthy",
      "total_servers": 24,
      "active_servers": 22,
      "shutoff_servers": 2,
      "error_servers": 0,
      "other_servers": 0,
      "total_vcpus": 96,
      "total_ram_mb": 196608,
      "total_flavor_disk_gb": 480,
      "active_vcpus": 88,
      "active_ram_mb": 180224,
      "hypervisor_count": 4,
      "power_on_pct": 91.67,
      "total_volumes": 48,
      "error_volumes": 1,
      "total_networks": 6,
      "total_snapshots": 120,
      "compliance_pct": 96.5,
      "total_drift_events": 3,
      "critical_drift_events": 0,
      "warning_drift_events": 2
    }
  ]
}
```

**Health Status Thresholds**:
| Status | Score Range |
|--------|-------------|
| `healthy` | 80–100 |
| `warning` | 50–79 |
| `critical` | 0–49 |

### Tenant Health Detail
**GET** `/tenant-health/{project_id}` (Authenticated, `tenant_health:read`)
Returns full detail for a single tenant including resource status breakdown, top volumes, and recent drift events.

Path Parameters:
- `project_id` (required) - Project UUID

Response:
```json
{
  "project_id": "abc-123",
  "project_name": "Production",
  "domain_name": "Default",
  "health_score": 95,
  "health_status": "healthy",
  "resources": {
    "servers": {
      "total": 24,
      "active": 22,
      "shutoff": 2,
      "error": 0
    },
    "volumes": {
      "total": 48,
      "available": 10,
      "in_use": 37,
      "error": 1
    },
    "snapshots": {
      "total": 120,
      "available": 118,
      "error": 2
    },
    "networks": {
      "total": 6
    }
  },
  "compliance_pct": 96.5,
  "top_volumes": [
    {
      "volume_id": "vol-001",
      "volume_name": "db-primary",
      "size_gb": 500,
      "status": "in-use",
      "attached_to": "db-server-01"
    }
  ],
  "recent_drift_events": [
    {
      "id": 42,
      "resource_type": "server",
      "resource_name": "web-03",
      "field_name": "status",
      "old_value": "ACTIVE",
      "new_value": "SHUTOFF",
      "severity": "critical",
      "detected_at": "2026-02-15T14:30:00Z"
    }
  ]
}
```

### Tenant Health Trends
**GET** `/tenant-health/trends/{project_id}` (Authenticated, `tenant_health:read`)
Returns daily drift and snapshot trend counts for chart visualizations.

Path Parameters:
- `project_id` (required) - Project UUID

Query Parameters:
- `days` (optional, default: 30) - Number of days of trend data

Response:
```json
{
  "project_id": "abc-123",
  "project_name": "Production",
  "period_days": 30,
  "trends": [
    {
      "date": "2026-02-15",
      "drift_events": 2,
      "snapshots_created": 5,
      "compliance_pct": 96.5,
      "health_score": 95
    },
    {
      "date": "2026-02-14",
      "drift_events": 0,
      "snapshots_created": 5,
      "compliance_pct": 97.0,
      "health_score": 97
    }
  ]
}
```

---

**GET** `/tenant-health/heatmap` (Authenticated, `tenant_health:read`)
Returns per-tenant resource utilization data for heatmap visualization. Each tenant gets a weighted utilization score (60% VM activity + 40% volume usage).

Query Parameters:
- `domain_id` (optional) - Filter by domain UUID

Response:
```json
{
  "tenants": [
    {
      "project_id": "abc-123",
      "project_name": "Production",
      "domain_name": "Default",
      "health_score": 95,
      "total_servers": 10,
      "active_servers": 8,
      "shutoff_servers": 2,
      "error_servers": 0,
      "total_vcpus": 40,
      "active_vcpus": 32,
      "total_ram_mb": 81920,
      "active_ram_mb": 65536,
      "power_on_pct": 80.0,
      "total_volumes": 15,
      "total_volume_gb": 500,
      "total_drift_events": 3,
      "critical_drift": 1,
      "compliance_pct": 96.5,
      "utilization_score": 72.4
    }
  ]
}
```

---

**GET** `/tenant-health/quota/{project_id}` (Authenticated, `tenant_health:read`)
Returns live OpenStack quota usage for a project. Fetches compute quotas (instances, cores, RAM) and storage quotas (volumes, gigabytes, snapshots) directly from OpenStack. Returns `available: false` gracefully when credentials are not configured.

Path Parameters:
- `project_id` (required) - Project UUID

Response (when available):
```json
{
  "available": true,
  "project_id": "abc-123",
  "compute": {
    "instances": { "limit": 50, "in_use": 10, "reserved": 0 },
    "cores": { "limit": 200, "in_use": 40, "reserved": 0 },
    "ram_mb": { "limit": 204800, "in_use": 81920, "reserved": 0 }
  },
  "storage": {
    "volumes": { "limit": 100, "in_use": 15, "reserved": 0 },
    "gigabytes": { "limit": 5000, "in_use": 500, "reserved": 0 },
    "snapshots": { "limit": 50, "in_use": 8, "reserved": 0 }
  }
}
```

Response (when unavailable):
```json
{
  "available": false,
  "reason": "OpenStack credentials not configured"
}
```

---

## Error Responses

All endpoints return standard error responses:

### 400 Bad Request
```json
{
  "detail": "Invalid parameter: limit must be between 1 and 20"
}
```

### 401 Unauthorized
```json
{
  "detail": "Not authenticated"
}
```

### 403 Forbidden
```json
{
  "detail": "Permission denied: requires dashboard:read"
}
```

### 404 Not Found
```json
{
  "detail": "Resource not found"
}
```

### 500 Internal Server Error
```json
{
  "detail": "Internal server error",
  "request_id": "abc-123-def"
}
```

---

## Rate Limiting

- Login endpoint: 10 requests per minute per IP
- Other endpoints: 100 requests per minute per user

Rate limit headers:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1675843200
```

---

## Pagination

Endpoints supporting pagination accept:
- `limit` - Results per page (default: 100, max: 1000)
- `offset` - Starting position (default: 0)

Response includes:
```json
{
  "total": 500,
  "limit": 100,
  "offset": 0,
  "results": [...]
}
```

---

**API Version**: 1.10  
**Last Updated**: February 2026  
**Base URL**: http://localhost:8000  
**Documentation**: http://localhost:8000/docs

---

## Department & Navigation Visibility Endpoints

### List Departments
**GET** `/api/departments`
*Requires: `departments:read`*

Returns all active departments.

### Create Department
**POST** `/api/departments`
*Requires: `departments:admin`*

```json
{ "name": "Engineering", "description": "Engineering team", "sort_order": 1 }
```

### Update Department
**PUT** `/api/departments/{id}`
*Requires: `departments:admin`*

### Delete Department
**DELETE** `/api/departments/{id}`
*Requires: `departments:admin`*

### List Navigation Groups
**GET** `/api/nav/groups`
*Requires: `navigation:read`*

### Create Navigation Group
**POST** `/api/nav/groups`
*Requires: `navigation:admin`*

### Update Navigation Group
**PUT** `/api/nav/groups/{id}`
*Requires: `navigation:admin`*

### Delete Navigation Group
**DELETE** `/api/nav/groups/{id}`
*Requires: `navigation:admin`*

### List Navigation Items
**GET** `/api/nav/items`
*Requires: `navigation:read`*

### Create Navigation Item
**POST** `/api/nav/items`
*Requires: `navigation:admin`*

### Update Navigation Item
**PUT** `/api/nav/items/{id}`
*Requires: `navigation:admin`*

### Delete Navigation Item
**DELETE** `/api/nav/items/{id}`
*Requires: `navigation:admin`*

### Get Department Visibility
**GET** `/api/departments/{id}/visibility`
*Requires: `navigation:read`*

Returns which nav groups and items are visible for a department.

### Update Department Visibility
**PUT** `/api/departments/{id}/visibility`
*Requires: `navigation:admin`*

```json
{ "nav_group_ids": [1, 2, 3], "nav_item_ids": [1, 2, 5, 8] }
```

### Get Visibility Matrix
**GET** `/api/departments/visibility/matrix`
*Requires: `navigation:admin`*

Returns the full department × nav item visibility matrix for the admin checkbox editor.

### Get User Navigation Overrides
**GET** `/api/nav/overrides/{username}`
*Requires: `navigation:admin`*

### Set User Navigation Override
**POST** `/api/nav/overrides/{username}`
*Requires: `navigation:admin`*

```json
{ "nav_item_id": 5, "override_type": "deny", "reason": "Not needed for this user" }
```

### Delete User Navigation Override
**DELETE** `/api/nav/overrides/{username}/{nav_item_id}`
*Requires: `navigation:admin`*

### Assign User Department
**PUT** `/api/auth/users/{username}/department`
*Requires: `users:admin`*

```json
{ "department_id": 3 }
```

### Get My Navigation
**GET** `/api/auth/me/navigation`
*Requires: authentication*

Returns the current user's complete navigation tree, including:
- User profile (username, role, department)
- Grouped navigation items (filtered by department visibility + per-user overrides)
- Permission entries for RBAC checks

---

## Branding & Settings Endpoints

### Get Branding
**GET** `/settings/branding`  
*Public — no authentication required* (so the login page can load branding)

Returns the current branding configuration.

Response:
```json
{
  "company_name": "CCC",
  "company_subtitle": "Infrastructure Management",
  "company_logo_url": "/static/logos/logo.png",
  "primary_color": "#667eea",
  "secondary_color": "#764ba2",
  "login_hero_title": "Welcome to PF9 Management",
  "login_hero_description": "Enterprise-grade OpenStack infrastructure management.",
  "login_hero_features": [
    "Real-time monitoring & alerting",
    "Automated snapshot management",
    "Full audit trail & compliance"
  ]
}
```

### Update Branding
**PUT** `/settings/branding`  
*Requires: `settings:admin` permission*

Request:
```json
{
  "company_name": "CCC",
  "company_subtitle": "Infrastructure Management",
  "primary_color": "#667eea",
  "secondary_color": "#764ba2",
  "login_hero_title": "Welcome to PF9 Management",
  "login_hero_description": "Enterprise-grade OpenStack infrastructure management.",
  "login_hero_features": ["Feature 1", "Feature 2"]
}
```

### Upload Logo
**POST** `/settings/branding/logo`  
*Requires: `settings:admin` permission*

Multipart file upload. Accepts PNG, JPEG, GIF, SVG, WebP. Max 2 MB.

Response:
```json
{
  "logo_url": "/static/logos/company_logo_1708099200.png"
}
```

### Get User Preferences
**GET** `/user-preferences`  
*Requires authentication*

Returns the current user’s preferences.

Response:
```json
{
  "tab_order": ["dashboard", "servers", "volumes", "snapshots", ...],
  "custom_setting": "value"
}
```

### Update User Preferences
**PUT** `/user-preferences`  
*Requires authentication*

Request:
```json
{
  "tab_order": ["dashboard", "volumes", "servers", "snapshots", ...]
}
```

Response:
```json
{
  "status": "saved",
  "username": "admin"
}
```

---

## Notification Endpoints

### Get SMTP Status
**GET** `/notifications/smtp-status`  
*Requires: `notifications:read`*

Response:
```json
{
  "smtp_enabled": true,
  "smtp_host": "smtp.example.com",
  "smtp_port": 25,
  "smtp_use_tls": false,
  "smtp_has_auth": false,
  "smtp_from": "pf9-mgmt@pf9mgmt.local"
}
```

### Get Notification Preferences
**GET** `/notifications/preferences`  
*Requires: `notifications:read`*

Response:
```json
[
  {
    "id": 1,
    "username": "admin",
    "event_type": "drift_critical",
    "email": "admin@company.com",
    "enabled": true,
    "severity_min": "warning",
    "delivery_mode": "immediate",
    "created_at": "2026-02-16T10:30:00Z",
    "updated_at": "2026-02-16T10:30:00Z"
  }
]
```

### Create/Update Notification Preference
**PUT** `/notifications/preferences`  
*Requires: `notifications:write`*

Request:
```json
{
  "event_type": "drift_critical",
  "email": "admin@company.com",
  "enabled": true,
  "severity_min": "warning",
  "delivery_mode": "immediate"
}
```

Response:
```json
{
  "status": "saved",
  "id": 1
}
```

### Delete Notification Preference
**DELETE** `/notifications/preferences/{id}`  
*Requires: `notifications:write`*

Response:
```json
{
  "status": "deleted"
}
```

### Get Notification History
**GET** `/notifications/history?limit=50&offset=0`  
*Requires: `notifications:read`*

Response:
```json
{
  "items": [
    {
      "id": 42,
      "username": "admin",
      "event_type": "drift_critical",
      "event_id": "123",
      "subject": "Drift Alert: server power_state changed",
      "recipient": "admin@company.com",
      "status": "sent",
      "sent_at": "2026-02-16T12:00:00Z",
      "error_message": null
    }
  ],
  "total": 1
}
```

### Send Test Email
**POST** `/notifications/test-email`  
*Requires: `notifications:admin`*

Request:
```json
{
  "recipient": "admin@company.com"
}
```

Response:
```json
{
  "status": "sent",
  "message": "Test email sent to admin@company.com"
}
```

### Get Admin Notification Statistics
**GET** `/notifications/admin/stats`  
*Requires: `notifications:admin`*

Response:
```json
{
  "total_sent": 156,
  "total_failed": 3,
  "total_pending": 0,
  "total_preferences": 12,
  "active_users": 4,
  "last_sent_at": "2026-02-16T12:00:00Z",
  "events_by_type": {
    "drift_critical": 45,
    "drift_warning": 67,
    "snapshot_failure": 12,
    "compliance_violation": 29,
    "health_score_drop": 3
  }
}
```

---

## Metering Endpoints

All metering endpoints require `metering:read` permission (admin/superadmin). Config update requires `metering:write` (superadmin only).

### Get Metering Configuration
**GET** `/api/metering/config`  
*Requires: `metering:read`*

Response:
```json
{
  "enabled": true,
  "collection_interval_min": 15,
  "retention_days": 90,
  "cost_per_vcpu_hour": 0.05,
  "cost_per_gb_ram_hour": 0.01,
  "cost_per_gb_storage_month": 0.10,
  "cost_per_snapshot_gb_month": 0.05,
  "cost_per_api_call": 0.0001,
  "cost_currency": "USD",
  "updated_at": "2026-02-20T10:00:00Z"
}
```

### Update Metering Configuration
**PUT** `/api/metering/config`  
*Requires: `metering:write`*

Request (all fields optional):
```json
{
  "enabled": true,
  "collection_interval_min": 30,
  "retention_days": 120,
  "cost_per_vcpu_hour": 0.08,
  "cost_per_gb_ram_hour": 0.02,
  "cost_per_gb_storage_month": 0.15,
  "cost_per_snapshot_gb_month": 0.08,
  "cost_per_api_call": 0.0002,
  "cost_currency": "EUR"
}
```

Response: Same as GET config.

### Metering Overview
**GET** `/api/metering/overview`  
*Requires: `metering:read`*

Query Parameters:
- `project` (optional) - Filter by project name
- `domain` (optional) - Filter by domain

Response:
```json
{
  "total_vms_metered": 145,
  "resources": {
    "total_vcpus": 580,
    "total_ram_mb": 1187840,
    "total_disk_gb": 14500,
    "avg_cpu_usage": 42.5,
    "avg_ram_usage": 65.3,
    "avg_disk_usage": 55.8
  },
  "snapshots": {
    "total_snapshots": 267,
    "total_snapshot_gb": 1840,
    "compliant_count": 245,
    "non_compliant_count": 22
  },
  "restores": {
    "total_restores": 12,
    "successful": 10,
    "failed": 2,
    "avg_duration_sec": 180.5
  },
  "api_usage": {
    "total_api_calls": 15420,
    "total_api_errors": 23,
    "avg_api_latency_ms": 45.2
  },
  "efficiency": {
    "avg_efficiency": 72.5,
    "excellent_count": 25,
    "good_count": 60,
    "fair_count": 35,
    "poor_count": 15,
    "idle_count": 10
  }
}
```

### Resource Metering
**GET** `/api/metering/resources`  
*Requires: `metering:read`*

Query Parameters:
- `project` (optional) - Filter by project name
- `domain` (optional) - Filter by domain
- `vm_id` (optional) - Filter by VM ID
- `hours` (default: 24, max: 2160) - Lookback window
- `limit` (default: 500, max: 10000) - Result limit

Response:
```json
{
  "data": [
    {
      "id": 1,
      "collected_at": "2026-02-20T10:15:00Z",
      "vm_id": "vm-abc123",
      "vm_name": "web-server-01",
      "project_name": "Production",
      "domain": "Default",
      "host": "compute-01",
      "flavor": "m1.large",
      "vcpus_allocated": 4,
      "ram_allocated_mb": 8192,
      "disk_allocated_gb": 80,
      "cpu_usage_percent": 45.2,
      "ram_usage_mb": 6144.0,
      "ram_usage_percent": 75.0,
      "disk_used_gb": 52.3,
      "disk_usage_percent": 65.4,
      "network_rx_bytes": 1048576,
      "network_tx_bytes": 524288,
      "status": "ACTIVE",
      "power_state": "running"
    }
  ],
  "count": 1
}
```

### Snapshot Metering
**GET** `/api/metering/snapshots`  
*Requires: `metering:read`*

Query Parameters:
- `project` (optional) - Filter by project name
- `domain` (optional) - Filter by domain
- `hours` (default: 24, max: 2160) - Lookback window
- `limit` (default: 500, max: 10000) - Result limit

Response:
```json
{
  "data": [
    {
      "id": 1,
      "collected_at": "2026-02-20T10:15:00Z",
      "snapshot_id": "snap-xyz789",
      "snapshot_name": "daily-backup-vol-01",
      "volume_id": "vol-456",
      "project_name": "Production",
      "domain": "Default",
      "size_gb": 50.0,
      "status": "available",
      "policy": "daily_5",
      "is_compliant": true,
      "created_at": "2026-02-20T02:00:00Z"
    }
  ],
  "count": 1
}
```

### Restore Metering
**GET** `/api/metering/restores`  
*Requires: `metering:read`*

Query Parameters:
- `project` (optional) - Filter by project name
- `domain` (optional) - Filter by domain
- `hours` (default: 168, max: 2160) - Lookback window
- `limit` (default: 200, max: 5000) - Result limit

Response:
```json
{
  "data": [
    {
      "id": 1,
      "collected_at": "2026-02-20T10:15:00Z",
      "restore_job_id": "job-abc123",
      "vm_id": "vm-old-456",
      "vm_name": "database-master",
      "project_name": "Production",
      "domain": "Default",
      "snapshot_id": "snap-xyz789",
      "mode": "NEW",
      "status": "completed",
      "duration_seconds": 145,
      "initiated_by": "admin",
      "data_transferred_gb": 50.0
    }
  ],
  "count": 1
}
```

### API Usage Metering
**GET** `/api/metering/api-usage`  
*Requires: `metering:read`*

Query Parameters:
- `endpoint` (optional) - Filter by endpoint path (partial match)
- `hours` (default: 24, max: 2160) - Lookback window
- `limit` (default: 500, max: 10000) - Result limit

Response:
```json
{
  "data": [
    {
      "id": 1,
      "collected_at": "2026-02-20T10:15:00Z",
      "endpoint": "/servers",
      "method": "GET",
      "total_calls": 250,
      "error_count": 2,
      "avg_latency_ms": 45.2,
      "p95_latency_ms": 120.0,
      "p99_latency_ms": 350.0
    }
  ],
  "count": 1
}
```

### Efficiency Scores
**GET** `/api/metering/efficiency`  
*Requires: `metering:read`*

Query Parameters:
- `project` (optional) - Filter by project name
- `domain` (optional) - Filter by domain
- `classification` (optional) - Filter: `excellent`, `good`, `fair`, `poor`, `idle`
- `hours` (default: 24, max: 2160) - Lookback window
- `limit` (default: 500, max: 10000) - Result limit

Response:
```json
{
  "data": [
    {
      "id": 1,
      "collected_at": "2026-02-20T10:15:00Z",
      "vm_id": "vm-abc123",
      "vm_name": "web-server-01",
      "project_name": "Production",
      "domain": "Default",
      "cpu_score": 75.0,
      "ram_score": 80.0,
      "disk_score": 65.0,
      "overall_score": 73.3,
      "classification": "good",
      "recommendation": "Consider right-sizing disk allocation"
    }
  ],
  "count": 1
}
```

### CSV Export Endpoints

All export endpoints return `text/csv` responses with `Content-Disposition` header.

| Endpoint | Description | Parameters |
|----------|-------------|------------|
| `GET /api/metering/export/resources` | Resource metering CSV | `project`, `domain`, `hours` |
| `GET /api/metering/export/snapshots` | Snapshot metering CSV | `project`, `domain`, `hours` |
| `GET /api/metering/export/restores` | Restore metering CSV | `project`, `domain`, `hours` |
| `GET /api/metering/export/api-usage` | API usage CSV | `hours` |
| `GET /api/metering/export/efficiency` | Efficiency scores CSV | `project`, `domain`, `hours` |
| `GET /api/metering/export/chargeback` | Chargeback report CSV | `project`, `domain`, `hours` |

*All require: `metering:read`*

**Chargeback Report** aggregates per-tenant resource usage and applies cost rates from both `metering_pricing` (multi-category: flavor, storage, snapshot, restore, volume, network) and fallback rates from `metering_config`. Output includes per-category cost columns and a TOTAL cost per tenant.

---

## Metering Pricing Endpoints

All pricing endpoints require `metering:read` for GET and `metering:write` for POST/PUT/DELETE.

### List All Pricing
**GET** `/api/metering/pricing`  
*Requires: `metering:read`*

Response:
```json
[
  {
    "id": 1,
    "category": "flavor",
    "item_name": "m1.large",
    "unit": "per hour",
    "cost_per_hour": 0.12,
    "cost_per_month": 87.60,
    "currency": "USD",
    "notes": null,
    "vcpus": 4,
    "ram_gb": 8.0,
    "disk_gb": 80.0,
    "auto_populated": false,
    "created_at": "2026-02-17T10:00:00Z",
    "updated_at": "2026-02-17T10:00:00Z"
  },
  {
    "id": 2,
    "category": "storage_gb",
    "item_name": "Storage (per GB)",
    "unit": "per GB/month",
    "cost_per_hour": 0,
    "cost_per_month": 0.10,
    "currency": "USD",
    "notes": "Block storage",
    "vcpus": null,
    "ram_gb": null,
    "disk_gb": null,
    "auto_populated": false,
    "created_at": "2026-02-17T10:00:00Z",
    "updated_at": "2026-02-17T10:00:00Z"
  }
]
```

Categories: `flavor`, `storage_gb`, `snapshot_gb`, `restore`, `volume`, `network`, `custom`

### Create Pricing Entry
**POST** `/api/metering/pricing`  
*Requires: `metering:write`*

Request:
```json
{
  "category": "storage_gb",
  "item_name": "Storage (per GB)",
  "unit": "per GB/month",
  "cost_per_hour": 0,
  "cost_per_month": 0.10,
  "currency": "USD",
  "notes": "Block storage pricing"
}
```

### Update Pricing Entry
**PUT** `/api/metering/pricing/{id}`  
*Requires: `metering:write`*

Request (all fields optional):
```json
{
  "cost_per_hour": 0.15,
  "cost_per_month": 109.50
}
```

### Delete Pricing Entry
**DELETE** `/api/metering/pricing/{id}`  
*Requires: `metering:write`*

### Sync Flavors from System
**POST** `/api/metering/pricing/sync-flavors`  
*Requires: `metering:write`*

Imports all flavors from the OpenStack flavors table into pricing. Skips flavors that already have a pricing entry.

Response:
```json
{
  "detail": "Synced 38 new flavors (0 already existed)",
  "inserted": 38
}
```

### Get Filter Data
**GET** `/api/metering/filters`  
*Requires: `metering:read`*

Returns dropdown filter options populated from actual data.

Response:
```json
{
  "projects": ["project-alpha", "project-beta", "org-main", "service"],
  "domains": ["example.com", "org1.example.com"],
  "all_tenants": [
    {"project": "project-alpha", "domain": "project-alpha"},
    {"project": "org-main", "domain": "org-main"}
  ],
  "flavors": [
    {"name": "m1.large", "vcpus": 4, "ram_mb": 8192, "disk_gb": 80}
  ]
}
```

---

## Runbook Endpoints

All runbook endpoints require authentication via `Authorization: Bearer <token>`.

### List Runbooks
**GET** `/api/runbooks`
*Requires: `runbooks:read`*

Returns all registered runbook definitions.

Response:
```json
[
  {
    "runbook_id": "uuid",
    "name": "stuck_vm_remediation",
    "display_name": "Stuck VM Remediation",
    "description": "Detects VMs stuck in BUILD, ERROR, or transitional states...",
    "category": "vm",
    "risk_level": "medium",
    "supports_dry_run": true,
    "enabled": true,
    "parameters_schema": {
      "type": "object",
      "properties": {
        "stuck_threshold_minutes": {"type": "integer", "default": 30},
        "action": {"type": "string", "enum": ["soft_reboot", "hard_reboot", "report_only"]},
        "target_project": {"type": "string", "default": ""},
        "target_domain": {"type": "string", "default": ""}
      }
    }
  }
]
```

### Get Single Runbook
**GET** `/api/runbooks/{runbook_name}`
*Requires: `runbooks:read`*

Returns a single runbook definition by name.

### Trigger Runbook
**POST** `/api/runbooks/trigger`
*Requires: `runbooks:write`*

Triggers a runbook execution. Depending on approval policies, the execution may auto-approve or enter `pending_approval` status.

Request:
```json
{
  "runbook_name": "orphan_resource_cleanup",
  "dry_run": true,
  "parameters": {
    "resource_types": ["ports", "volumes"],
    "age_threshold_days": 7,
    "target_project": ""
  }
}
```

Response:
```json
{
  "execution_id": "uuid",
  "runbook_name": "orphan_resource_cleanup",
  "status": "completed",
  "dry_run": true,
  "parameters": {},
  "result": {"orphan_ports": [], "orphan_volumes": []},
  "triggered_by": "admin",
  "triggered_at": "2026-02-19T10:30:00Z",
  "items_found": 5,
  "items_actioned": 0
}
```

#### New Runbook Trigger Examples (v1.25)

**VM Health Quick Fix** — diagnose a single VM:
```json
{
  "runbook_name": "vm_health_quickfix",
  "dry_run": false,
  "parameters": {
    "server_id": "abc123-...",
    "auto_restart": false,
    "restart_type": "soft"
  }
}
```

**Snapshot Before Escalation** — create a tagged snapshot before T2 handoff:
```json
{
  "runbook_name": "snapshot_before_escalation",
  "dry_run": false,
  "parameters": {
    "server_id": "abc123-...",
    "tag_prefix": "Pre-T2-escalation",
    "reference_id": "INC-2026-0042"
  }
}
```

**Upgrade Opportunity Detector** — scan for upsell signals:
```json
{
  "runbook_name": "upgrade_opportunity_detector",
  "dry_run": false,
  "parameters": {
    "quota_threshold_pct": 80,
    "include_flavor_analysis": true,
    "include_image_analysis": true,
    "price_per_vcpu": 15.0,
    "price_per_gb_ram": 5.0
  }
}
```

**Monthly Executive Snapshot** — generate executive report:
```json
{
  "runbook_name": "monthly_executive_snapshot",
  "dry_run": false,
  "parameters": {
    "risk_top_n": 5,
    "include_deltas": true,
    "price_per_vcpu": 15.0,
    "price_per_gb_storage": 2.0
  }
}
```

**Cost Leakage Report** — identify wasted infrastructure spend:
```json
{
  "runbook_name": "cost_leakage_report",
  "dry_run": false,
  "parameters": {
    "idle_cpu_threshold_pct": 5,
    "shutoff_days_threshold": 30,
    "detached_volume_days": 7,
    "price_per_vcpu_month": 15.0,
    "price_per_gb_volume_month": 2.0,
    "price_per_floating_ip_month": 5.0
  }
}
```

**Password Reset + Console Access** — reset password and get console URL (requires approval for non-superadmin):
```json
{
  "runbook_name": "password_reset_console",
  "dry_run": true,
  "parameters": {
    "server_id": "abc123-...",
    "new_password": "",
    "enable_console": true,
    "console_expiry_minutes": 30
  }
}
```

**Security & Compliance Audit** — extended security scan:
```json
{
  "runbook_name": "security_compliance_audit",
  "dry_run": false,
  "parameters": {
    "stale_user_days": 90,
    "flag_wide_port_ranges": true,
    "check_volume_encryption": true
  }
}
```

**Snapshot Quota Forecast** (v1.26.0) — proactive quota vs. policy analysis per tenant:
```json
{
  "runbook_name": "snapshot_quota_forecast",
  "dry_run": false,
  "parameters": {
    "include_pending_policies": true,
    "safety_margin_pct": 10
  }
}
```

### Approve or Reject Execution
**POST** `/api/runbooks/executions/{execution_id}/approve`
*Requires: `runbooks:admin`*

Approve or reject a pending execution.

Request:
```json
{
  "decision": "approved",
  "comment": "Looks good, proceed"
}
```

### Cancel Execution
**POST** `/api/runbooks/executions/{execution_id}/cancel`
*Requires: `runbooks:write`*

Cancels a pending or executing runbook run.

### Get Execution History
**GET** `/api/runbooks/executions/history`
*Requires: `runbooks:read`*

Query parameters: `runbook_name`, `status`, `limit` (default 25), `offset` (default 0).

Response:
```json
{
  "executions": [
    {
      "execution_id": "uuid",
      "runbook_name": "security_group_audit",
      "display_name": "Security Group Audit",
      "category": "security",
      "risk_level": "low",
      "status": "completed",
      "dry_run": true,
      "triggered_by": "operator",
      "triggered_at": "2026-02-19T10:30:00Z",
      "items_found": 3,
      "items_actioned": 0
    }
  ],
  "total": 42
}
```

### Get Execution Detail
**GET** `/api/runbooks/executions/{execution_id}`
*Requires: `runbooks:read`*

Returns full execution detail including parameters, result JSON, and approval history.

### Get Pending Approvals
**GET** `/api/runbooks/approvals/pending`
*Requires: `runbooks:admin`*

Returns all executions in `pending_approval` status awaiting admin action.

### List Policies for Runbook
**GET** `/api/runbooks/policies/{runbook_name}`
*Requires: `runbooks:read`*

Returns all approval policies for a given runbook.

Response:
```json
[
  {
    "policy_id": "uuid",
    "runbook_name": "stuck_vm_remediation",
    "trigger_role": "operator",
    "approver_role": "admin",
    "approval_mode": "single_approval",
    "escalation_timeout_minutes": 60,
    "max_auto_executions_per_day": 50,
    "enabled": true
  }
]
```

### Create or Update Policy
**PUT** `/api/runbooks/policies/{runbook_name}`
*Requires: `runbooks:admin`*

Request:
```json
{
  "trigger_role": "operator",
  "approver_role": "admin",
  "approval_mode": "single_approval",
  "escalation_timeout_minutes": 60,
  "max_auto_executions_per_day": 50
}
```

### Delete Policy
**DELETE** `/api/runbooks/policies/{policy_id}`
*Requires: `runbooks:admin`*

### Execution Stats Summary
**GET** `/api/runbooks/stats/summary`
*Requires: `runbooks:read`*

Returns aggregated execution statistics per runbook.

Response:
```json
[
  {
    "runbook_name": "orphan_resource_cleanup",
    "total_executions": 15,
    "completed": 12,
    "failed": 1,
    "pending": 2,
    "rejected": 0,
    "total_items_found": 47,
    "total_items_actioned": 23,
    "last_run": "2026-02-19T10:30:00Z"
  }
]
```

---

## Ops Copilot Endpoints

All Copilot endpoints are under `/api/copilot` and require authentication.

### Ask a Question
**POST** `/api/copilot/ask`
*Requires: authentication*

Send a natural-language question. The engine first tries the built-in intent matcher (40+ intents with tenant/project/host scoping and synonym expansion), then falls back to the configured LLM backend.

Some intents call live Platform9 APIs instead of SQL queries (e.g., `configured_quota` fetches quota limits from Nova/Cinder/Neutron in real time).

Request:
```json
{
  "question": "How many powered on VMs on tenant production?"
}
```

Response:
```json
{
  "answer": "📌 *Filtered by tenant/project: **production***\n\nThere are **5** powered-on (active) VMs.",
  "intent": "powered_on_vms",
  "backend_used": "builtin",
  "confidence": 1.0,
  "tokens_used": null,
  "data_sent_external": false,
  "history_id": 42
}
```

**Scoping**: Append `on tenant <name>`, `for project <name>`, or `on host <hostname>` to any question. The engine dynamically injects SQL WHERE clauses to filter results.

**Synonym expansion**: Words like "powered on" → "active", "vm" → "vms", "tenant" → "project" are expanded automatically for higher match accuracy.

### Get Suggestion Chips
**GET** `/api/copilot/suggestions`
*Requires: authentication*

Returns categorized quick-start questions organized into 8 groups, plus usage tips.

Response:
```json
{
  "suggestions": {
    "categories": [
      {
        "name": "Infrastructure",
        "icon": "🖥️",
        "chips": [
          { "label": "How many VMs?", "question": "How many VMs?" },
          { "label": "List all hosts", "question": "List all hosts" }
        ]
      },
      {
        "name": "VM Power State",
        "icon": "⚡",
        "chips": [
          { "label": "Powered on VMs", "question": "How many powered on VMs?" },
          { "label": "Powered off VMs", "question": "Show powered off VMs" }
        ]
      },
      {
        "name": "Tenant / Project",
        "icon": "📁",
        "chips": [
          { "label": "VMs on tenant …", "question": "VMs on tenant ", "template": true },
          { "label": "Quota for …", "question": "Quota of tenant ", "template": true },
          { "label": "Usage for …", "question": "Usage for tenant ", "template": true },
          { "label": "Quota & Usage …", "question": "Quota and usage for tenant ", "template": true }
        ]
      }
    ],
    "tips": [
      "Ask naturally: \"How many powered on VMs on tenant <your-tenant>?\"",
      "Scope by tenant: add \"on tenant <name>\" or \"for project <name>\"",
      "Scope by host: add \"on host <hostname>\"",
      "Use action words: show, list, count, how many",
      "Click any chip to run it instantly — chips with \"…\" need a name"
    ]
  }
}
```

> **Note**: `template: true` chips should fill the input field for the user to complete the tenant/project name. Regular chips execute immediately.

### Get Conversation History
**GET** `/api/copilot/history`
*Requires: authentication*

Returns the current user's conversation history (most recent 200 entries).

Response:
```json
[
  {
    "id": 42,
    "question": "How many VMs?",
    "answer": "There are **35** VMs across all tenants.",
    "intent": "vm_count",
    "backend_used": "builtin",
    "confidence": 1.0,
    "created_at": "2026-02-22T12:00:00Z"
  }
]
```

### Get Copilot Configuration
**GET** `/api/copilot/config`
*Requires: admin role*

Returns the current Copilot backend configuration.

Response:
```json
{
  "backend": "builtin",
  "ollama_url": "http://host.docker.internal:11434",
  "ollama_model": "llama3",
  "openai_model": "gpt-4o-mini",
  "anthropic_model": "claude-sonnet-4-20250514",
  "redact_sensitive": true,
  "system_prompt": "You are Ops Copilot, an AI assistant for Platform9 infrastructure management..."
}
```

### Update Copilot Configuration
**PUT** `/api/copilot/config`
*Requires: admin role*

Update the active backend and/or settings. Takes effect immediately.

Request:
```json
{
  "backend": "ollama",
  "ollama_url": "http://host.docker.internal:11434",
  "ollama_model": "llama3"
}
```

### Test LLM Connection
**POST** `/api/copilot/test-connection`
*Requires: admin role*

Test connectivity to the configured LLM backend.

Request:
```json
{
  "backend": "ollama",
  "ollama_url": "http://host.docker.internal:11434",
  "ollama_model": "llama3"
}
```

Response:
```json
{
  "success": true,
  "message": "Ollama connection successful",
  "latency_ms": 245
}
```

### Submit Feedback
**POST** `/api/copilot/feedback`
*Requires: authentication*

Submit thumbs up/down feedback on a Copilot answer.

Request:
```json
{
  "history_id": 42,
  "feedback": "up"
}
```

Response:
```json
{
  "status": "ok"
}
```

---

## Migration Planner

VMware → Platform9 PCD migration intelligence and execution endpoints. All endpoints are under `/api/migration/`.

**RBAC**: `migration` resource — `read` (browse), `write` (create/edit/upload/assess), `admin` (approve/delete).

### Create Migration Project
**POST** `/api/migration/projects`
*Requires: migration:write*

Create a new migration project in `draft` status.

Request:
```json
{
  "name": "Acme Corp VMware Migration",
  "description": "Q2 2026 migration from vSphere 7 to PCD"
}
```

Response:
```json
{
  "project": {
    "project_id": "a1b2c3d4-...",
    "name": "Acme Corp VMware Migration",
    "status": "draft",
    "topology_type": "local",
    "source_nic_speed_gbps": 10.0,
    "source_usable_pct": 40.0,
    "agent_count": 2,
    "agent_concurrent_vms": 5,
    "created_at": "2026-02-25T12:00:00Z"
  }
}
```

### List Migration Projects
**GET** `/api/migration/projects`
*Requires: migration:read*

Returns all non-archived migration projects ordered by creation date (newest first).

### Get Project Details
**GET** `/api/migration/projects/{project_id}`
*Requires: migration:read*

### Update Project Settings
**PATCH** `/api/migration/projects/{project_id}`
*Requires: migration:write*

Update topology, bandwidth settings, and agent profile. Accepts any subset of project fields.

Request:
```json
{
  "topology_type": "cross_site_dedicated",
  "link_speed_gbps": 1.0,
  "link_usable_pct": 60,
  "agent_count": 4,
  "agent_concurrent_vms": 3
}
```

### Delete Migration Project
**DELETE** `/api/migration/projects/{project_id}`
*Requires: migration:admin*

Permanently deletes the project and all child data (CASCADE).

### Upload RVTools XLSX
**POST** `/api/migration/projects/{project_id}/upload`
*Requires: migration:write*

Upload an RVTools XLSX export. Parses 6 sheets: vInfo, vDisk, vNIC, vHost, vCluster, vSnapshot. Fuzzy column matching handles RVTools version differences. Re-uploading replaces all source data.

Request: `multipart/form-data` with `file` field.

Response:
```json
{
  "stats": {
    "vInfo": 245,
    "vDisk": 512,
    "vNIC": 310,
    "vHost": 12,
    "vCluster": 3,
    "vSnapshot": 87
  }
}
```

### List VMs
**GET** `/api/migration/projects/{project_id}/vms`
*Requires: migration:read*

Paginated, sortable, filterable VM inventory.

Query Parameters:
- `page` (default: 1), `limit` (default: 50)
- `sort` (default: vm_name), `order` (asc/desc)
- `search` — fuzzy match on vm_name
- `risk_level` — GREEN, YELLOW, RED
- `migration_mode` — warm_eligible, warm_risky, cold_required
- `tenant` — filter by assigned tenant name
- `os_family` — filter by OS family: windows, linux, other
- `power_state` — filter by power state: poweredOn, poweredOff, suspended
- `cluster` — filter by cluster name

### VM Detail (Disks & NICs)
**GET** `/api/migration/projects/{project_id}/vms/{vm_name}/details`
*Requires: migration:read*

Returns per-disk and per-NIC records for a specific VM.

Response:
```json
{
  "vm_name": "web-prod-01",
  "disks": [
    {
      "disk_label": "Hard disk 1",
      "disk_path": "[DS01] web-prod-01/web-prod-01.vmdk",
      "capacity_gb": 100.0,
      "thin_provisioned": true,
      "eagerly_scrub": false,
      "datastore": "DS01"
    }
  ],
  "nics": [
    {
      "nic_label": "Network adapter 1",
      "adapter_type": "VMXNET3",
      "network_name": "VLAN-100-Prod",
      "connected": true,
      "mac_address": "00:50:56:ab:cd:ef",
      "ip_address": "10.0.1.50"
    }
  ]
}
```

### Export Migration Plan
**GET** `/api/migration/projects/{project_id}/export-plan`
*Requires: migration:read*

Generates a full migration plan with per-VM time estimates based on the project's bandwidth model. Includes per-tenant breakdowns and a daily migration schedule.

Response:
```json
{
  "project_summary": {
    "project_name": "Acme Corp Migration",
    "total_vms": 245,
    "warm_count": 198,
    "cold_count": 47,
    "total_disk_tb": 48.2,
    "bottleneck_mbps": 500,
    "estimated_total_hours": 1240.5,
    "estimated_days": 21
  },
  "tenant_plans": [
    {
      "tenant_name": "Org-Finance",
      "vm_count": 32,
      "warm_count": 28,
      "cold_count": 4,
      "total_disk_gb": 4800.0,
      "phase1_hours": 62.4,
      "cutover_hours": 8.2,
      "total_hours": 70.6,
      "risk_distribution": {"GREEN": 20, "YELLOW": 10, "RED": 2},
      "vms": [
        {
          "vm_name": "fin-db-01",
          "total_disk_gb": 500.0,
          "in_use_gb": 320.0,
          "mode": "warm_eligible",
          "risk_level": "GREEN",
          "warm_phase1_hours": 2.84,
          "warm_cutover_hours": 0.38,
          "warm_downtime_hours": 0.38,
          "cold_total_hours": 4.44,
          "cold_downtime_hours": 4.44
        }
      ]
    }
  ],
  "daily_schedule": [
    {
      "day": 1,
      "vms": ["fin-db-01", "fin-app-01", "fin-web-01", "hr-db-01", "hr-app-01"]
    }
  ]
}
```

### List Tenants
**GET** `/api/migration/projects/{project_id}/tenants`
*Requires: migration:read*

Returns detected tenants with aggregated VM counts and resource totals.

### Add Tenant Rule
**POST** `/api/migration/projects/{project_id}/tenants`
*Requires: migration:write*

Request:
```json
{
  "tenant_name": "acme",
  "detection_method": "folder_path",
  "pattern_value": "/Acme Corp/"
}
```

### Re-run Tenant Detection
**POST** `/api/migration/projects/{project_id}/tenants/detect`
*Requires: migration:write*

Re-applies all tenant rules to all VMs in the project.

### List Hosts
**GET** `/api/migration/projects/{project_id}/hosts`
*Requires: migration:read*

### List Clusters
**GET** `/api/migration/projects/{project_id}/clusters`
*Requires: migration:read*

### Get Stats
**GET** `/api/migration/projects/{project_id}/stats`
*Requires: migration:read*

Returns aggregated statistics including risk distribution, mode distribution, OS distribution, and total resource counts.

### Get / Update Risk Config
**GET** `/api/migration/projects/{project_id}/risk-config`
**PUT** `/api/migration/projects/{project_id}/risk-config`
*Requires: migration:write (PUT), migration:read (GET)*

View or update the risk scoring weights used by the assessment engine.

### Run Assessment
**POST** `/api/migration/projects/{project_id}/assess`
*Requires: migration:write*

Runs full assessment: tenant detection, risk scoring, migration mode classification, and time estimation for all VMs. Updates project status to `assessment`.

### Reset Assessment
**POST** `/api/migration/projects/{project_id}/reset-assessment`
*Requires: migration:write*

Clears all computed risk scores, migration modes, and time estimates. Retains source data.

### Reset Plan
**POST** `/api/migration/projects/{project_id}/reset-plan`
*Requires: migration:write*

Clears migration waves, wave-VM assignments, target gaps, and prep tasks. Retains assessment data.

### Approve Project
**POST** `/api/migration/projects/{project_id}/approve`
*Requires: migration:admin*

Transitions project to `approved` status. This is the gate that must be passed before any PCD target preparation or execution endpoints will accept requests.

### Bandwidth Model
**GET** `/api/migration/projects/{project_id}/bandwidth`
*Requires: migration:read*

Returns the 4-constraint bandwidth model with bottleneck identification.

Response:
```json
{
  "bandwidth": {
    "source_effective_mbps": 4000,
    "link_effective_mbps": 600,
    "agent_effective_mbps": 7000,
    "storage_effective_mbps": 500,
    "bottleneck": "pcd_storage",
    "bottleneck_mbps": 500,
    "latency_penalty": 1.0
  }
}
```

### Agent Sizing Recommendation
**GET** `/api/migration/projects/{project_id}/agent-recommendation`
*Requires: migration:read*

Returns recommended agent count, vCPU, RAM, and disk per agent based on current workload profile **and migration schedule**. The engine factors in `migration_duration_days`, `working_hours_per_day`, `working_days_per_week`, and `target_vms_per_day` when set on the project.

**Schedule-aware logic:**
- If `target_vms_per_day` > 0: derives agents needed to hit that daily throughput
- If `migration_duration_days` > 0: derives agents from `(total_vms / effective_working_days)` throughput needs
- Fallback: heuristic based on VM count and concurrent-per-agent

Response:
```json
{
  "recommendation": {
    "recommended_agent_count": 5,
    "vcpu_per_agent": 10,
    "ram_gb_per_agent": 7,
    "disk_gb_per_agent": 120,
    "max_concurrent_vms": 25,
    "reasoning": [
      "245 VMs in 30 days (5d/wk × 8h/d = 21 effective days)",
      "Need 11.7 VMs/day → 5 agents",
      "Recommended 5 agents = 25 concurrent slots",
      "Per agent: 10 vCPU, 7 GB RAM, 120 GB disk",
      "Estimated completion: ~10 working days (25 VMs/day capacity)"
    ]
  }
}
```

---

## Migration Planner Phase 2.10 Endpoints

> All Phase 2.10 endpoints are under `/api/migration/projects/{project_id}/...` and require `migration:read` unless noted.

### VM Migration Status

**PATCH** `/api/migration/projects/{project_id}/vms/{vm_id}/status`  
*Requires: migration:write*

Update single VM migration status.

Request:
```json
{ "status": "in_progress", "status_note": "Kick-off batch 3" }
```
Values: `not_started` | `assigned` | `in_progress` | `migrated` | `failed` | `skipped`

**PATCH** `/api/migration/projects/{project_id}/vms/bulk-status`  
*Requires: migration:write*

Update multiple VMs to the same status in one call.

Request:
```json
{ "vm_ids": [1, 2, 3], "status": "skipped", "status_note": "Out of scope" }
```

### VM Mode Override

**PATCH** `/api/migration/projects/{project_id}/vms/{vm_id}/mode-override`  
*Requires: migration:write*

Force warm/cold classification regardless of engine result. Send `null` to revert to engine classification.

Request:
```json
{ "override": "warm" }
```

### VM Dependencies

**GET** `/api/migration/projects/{project_id}/vm-dependencies`  
*Requires: migration:read*

List all VM dependency pairs for the project. Optional `?vm_id=N` to filter to a specific VM. Returns source and target VM names via JOIN.

**POST** `/api/migration/projects/{project_id}/vms/{vm_id}/dependencies`  
*Requires: migration:write*

Add a dependency: `vm_id` must complete before `depends_on_vm_id` starts. Returns 409 if a circular dependency is detected.

Request:
```json
{ "depends_on_vm_id": 42, "dependency_type": "must_complete_before", "notes": "DB before web tier" }
```

**DELETE** `/api/migration/projects/{project_id}/vms/{vm_id}/dependencies/{dep_id}`  
*Requires: migration:write*

Remove a dependency record.

### Network Mappings

**GET** `/api/migration/projects/{project_id}/network-mappings`  
*Requires: migration:read*

List all source→PCD network mappings. On each call, auto-seeds a `(source_network_name, target=source_name, confirmed=false)` row for any distinct `network_name` found in in-scope VMs that doesn't already have an entry. Returns `unconfirmed_count` (rows not yet confirmed by operator).

Response:
```json
{
  "mappings": [{"id": 1, "source_network_name": "VLAN-100", "target_network_name": "pf9-prod", "vlan_id": 100, "vm_count": 12, "confirmed": true}],
  "unconfirmed_count": 3
}
```

**POST** `/api/migration/projects/{project_id}/network-mappings`  
*Requires: migration:write*

Create or upsert a mapping.

Request:
```json
{ "source_network_name": "VLAN-100", "target_network_name": "pf9-prod", "target_network_id": "uuid", "notes": "" }
```

**PATCH** `/api/migration/projects/{project_id}/network-mappings/{mapping_id}`  
*Requires: migration:write*

Update target network name/ID, VLAN ID, or confirmed status on an existing mapping.

Request:
```json
{ "target_network_name": "pf9-dmz", "target_network_id": null, "vlan_id": 3314, "confirmed": true }
```

**POST** `/api/migration/projects/{project_id}/network-mappings/bulk-replace`  
*Requires: migration:write*

Find-and-replace in `target_network_name` across all mappings. Literal substring match (not regex). Affected rows are set to `confirmed=false`. Supports preview mode (dry-run).

Request:
```json
{
  "find": "_vLAN_",
  "replace": "-vlan-",
  "case_sensitive": false,
  "unconfirmed_only": false,
  "preview_only": true
}
```

Response (preview):
```json
{ "status": "ok", "preview": [{"id": 1, "source_network_name": "...", "old_value": "...", "new_value": "..."}], "affected_count": 5 }
```

**POST** `/api/migration/projects/{project_id}/network-mappings/confirm-all`  
*Requires: migration:write*

Mark all unconfirmed network mappings as confirmed in one call.

Response: `{ "status": "ok", "affected_count": 42 }`

**DELETE** `/api/migration/projects/{project_id}/network-mappings/{mapping_id}`  
*Requires: migration:admin*

Delete a mapping row.

### Cohorts

**GET** `/api/migration/projects/{project_id}/cohorts`  
*Requires: migration:read*

List cohorts with per-cohort tenant count, VM count, total vCPU/RAM/disk aggregated from in-scope VMs. Returns `unassigned_tenant_count`.

**POST** `/api/migration/projects/{project_id}/cohorts`  
*Requires: migration:write*

Create a cohort.

Request:
```json
{
  "name": "Wave Alpha — Low Risk",
  "cohort_order": 1,
  "owner_name": "Team Infra",
  "scheduled_start": "2026-04-01",
  "scheduled_end": "2026-04-14",
  "depends_on_cohort_id": null,
  "notes": ""
}
```

**PATCH** `/api/migration/projects/{project_id}/cohorts/{cohort_id}`  
*Requires: migration:write*

Update cohort fields (name, dates, order, owner, status, notes, depends_on_cohort_id).

**DELETE** `/api/migration/projects/{project_id}/cohorts/{cohort_id}`  
*Requires: migration:write*

Delete a cohort. All assigned tenants are unassigned (cohort_id set to NULL) before deletion.

**POST** `/api/migration/projects/{project_id}/cohorts/{cohort_id}/assign-tenants`  
*Requires: migration:write*

Assign or unassign tenant IDs to a cohort. Use `cohort_id = 0` in the URL to unassign.

Request:
```json
{ "tenant_ids": [1, 2, 5], "replace": false }
```

**GET** `/api/migration/projects/{project_id}/cohorts/{cohort_id}/summary`  
*Requires: migration:read*

Rollup: tenant count, VM count, total vCPU/RAM/disk, estimated migration hours, migration status breakdown.

**POST** `/api/migration/projects/{project_id}/cohorts/auto-assign`  
*Requires: migration:write*

Auto-assign all unassigned tenants across cohorts using the chosen strategy.

Query params: `?strategy=priority` (default) | `equal_split` | `risk`

### Tenant Readiness

**GET** `/api/migration/projects/{project_id}/tenants/{tenant_id}/readiness`  
*Requires: migration:read*

Compute and persist 5 readiness checks for the tenant. Returns overall pass/fail, score (0–5), and per-check details.

Response:
```json
{
  "tenant_id": 7,
  "overall": "pass",
  "score": 4,
  "checks": [
    {"check_name": "target_mapped", "check_status": "pass"},
    {"check_name": "network_mapped", "check_status": "fail", "notes": "2 unmapped networks"},
    {"check_name": "quota_sufficient", "check_status": "pass"},
    {"check_name": "no_critical_gaps", "check_status": "pass"},
    {"check_name": "vms_classified", "check_status": "pass"}
  ]
}
```

**GET** `/api/migration/projects/{project_id}/cohorts/{cohort_id}/readiness-summary`  
*Requires: migration:read*

Run readiness checks for every tenant in the cohort and return a summary table plus cohort-level overall status (`all_pass`, `partial`, `blocked`).

### Tenant Target Bulk Operations (v1.31.3+)

**POST** `/api/migration/projects/{project_id}/tenants/bulk-replace-target`  
*Requires: migration:write*

Find-and-replace in a target field across all tenant rows. Affected rows are set to `target_confirmed=false`. Supports preview mode (dry-run). Allowed fields: `target_domain_name`, `target_domain_description`, `target_project_name`, `target_display_name`.

Request:
```json
{
  "field": "target_project_name",
  "find": "_vDC_",
  "replace": "-",
  "case_sensitive": false,
  "unconfirmed_only": false,
  "preview_only": true
}
```

Response (preview):
```json
{
  "status": "ok",
  "preview": [{"id": 1, "tenant_name": "Org1", "org_vdc": "Dev", "old_value": "Org1_vDC_Dev", "new_value": "Org1-Dev"}],
  "affected_count": 18
}
```

**POST** `/api/migration/projects/{project_id}/tenants/confirm-all`  
*Requires: migration:write*

Mark all unconfirmed tenant target names as confirmed in one call.

Response: `{ "status": "ok", "affected_count": 34 }`

### Tenant Description Fields (v1.31.7+)

The `PATCH /projects/{id}/tenants/{tenant_id}` endpoint accepts two description fields in addition to name fields:

| Field | PCD Mapping | Notes |
|-------|------------|-------|
| `target_domain_name` | Domain name | Auto-seeded from `tenant_name` |
| `target_domain_description` | Domain description | Auto-seeded from `tenant_name`; editable |
| `target_project_name` | Project name | Auto-seeded from OrgVDC or tenant_name |
| `target_display_name` | Project description | Auto-seeded from project name; editable |
| `target_confirmed` | — | `true` = operator reviewed |

### Network Mapping VLAN Edit (v1.31.10+)

`PATCH /network-mappings/{id}` accepts `vlan_id` to allow operators to manually set or correct a VLAN ID that was not auto-parsed from the source network name. Send `null` to clear it.
