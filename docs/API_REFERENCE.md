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
