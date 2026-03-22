# Multi-Region & Multi-Cluster Guide

> **Audience**: MSP operators and enterprise administrators who manage more than one Platform9 installation, or who are setting up pf9-mngt for the first time and want to understand the multi-cluster architecture.

---

## Table of Contents

1. [Why Multi-Cluster — The MSP Use Case](#1-why-multi-cluster--the-msp-use-case)
2. [Architecture Overview](#2-architecture-overview)
3. [Zero-Migration Rollout](#3-zero-migration-rollout)
4. [Adding a Control Plane](#4-adding-a-control-plane)
5. [Registering Regions](#5-registering-regions)
6. [The Region Selector UI](#6-the-region-selector-ui)
7. [Cluster Management Admin Panel](#7-cluster-management-admin-panel)
8. [Per-Region API Filtering](#8-per-region-api-filtering)
9. [Multi-Region Workers](#9-multi-region-workers)
10. [Region Health & Status Monitoring](#10-region-health--status-monitoring)
11. [Migration Planning with Registered Regions](#11-migration-planning-with-registered-regions)
12. [Cross-Region Task Bus](#12-cross-region-task-bus)
13. [Security](#13-security)
14. [API Reference](#14-api-reference)
15. [Troubleshooting](#15-troubleshooting)

---

## 1. Why Multi-Cluster — The MSP Use Case

**The problem**: You manage 4 customers. Each customer runs their own Platform9 installation — separate Keystone, separate hypervisors, separate networks — in separate data centres. Today you context-switch between 4 portals, export CSVs from each one, and manually reconcile the data to answer the question "which of my customers has the worst snapshot compliance this month?"

**What pf9-mngt gives you**: A single console that connects to all 4. Every view — inventory, metering, snapshots, reports, migration planner — can be scoped to one customer with a dropdown, or aggregated across all customers simultaneously.

**Concrete outcomes**:
- **Per-customer billing**: metering data is tagged by region so monthly usage reports break down cleanly per customer
- **Unified snapshot SLA**: the Snapshot SLA dashboard shows compliance per customer side-by-side; you can see which customer's automated snapshots are failing without logging in to each portal
- **Cross-cluster migration planning**: if a customer wants to move workloads from their aging cluster to a new one, the Migration Planner can analyse both as registered regions and produce a gap analysis
- **Single audit trail**: all operator actions across all clusters are written to one activity log with `region_id` tagging
- **Disaster recovery**: the cross-region task bus (in progress) is designed to orchestrate snapshot replication across clusters so a customer's VM snapshots can be replicated to a second cluster

---

## 2. Architecture Overview

### Two-Level Hierarchy

A Platform9 control plane exposes one Keystone endpoint that authenticates users and returns a service catalog with per-region Nova, Neutron, Cinder, and Glance endpoint URLs. pf9-mngt maps this directly:

```
pf9-mngt
|
+-- Control Plane: "default"  (PF9_AUTH_URL -> Keystone /v3)
|   |   Identity scope: domains, projects, users, roles
|   +-- Region: "default:region-one"
|   |       Compute / Network / Storage / Image endpoints
|   |       VMs, Volumes, Networks, Hypervisors, Snapshots, ...
|   +-- Region: "default:eu-west-1"  (added via UI -- no restart needed)
|           Own endpoint set, own resource inventory
|
+-- Control Plane: "corp-dc2"  (separate Keystone, separate credentials)
    +-- Region: "corp-dc2:region-one"
    +-- ...
```

**Key rules:**
- **Keystone API calls** (list domains, list projects, create user) fire once per **control plane**
- **Nova / Neutron / Cinder / Glance API calls** fire per **region** (endpoint selected from service catalog by `region_name`)
- **Identity resources** (domains, projects, users, roles) carry a `control_plane_id` FK
- **Compute / network / storage resources** carry a `region_id` FK

### Database Tables

| Table | Purpose |
|---|---|
| `pf9_control_planes` | One row per PF9 installation: auth URL, encrypted credentials, health fields, SSRF guard flag |
| `pf9_regions` | One row per OpenStack region: parent control plane, `region_name`, `health_status`, capabilities JSONB |
| `cluster_sync_metrics` | Per-region sync outcomes: duration, resource counts, error count, avg latency |
| `cluster_tasks` | State machine for long-running cross-region operations |

### ClusterRegistry

`api/cluster_registry.py` is the single authoritative client hub. It holds one authenticated `Pf9Client` per enabled region, reusing TCP connections for all API calls in that region. All workers and API handlers call `ClusterRegistry` rather than constructing their own Keystone sessions.

---

## 3. Zero-Migration Rollout

**If you are already running a single-region pf9-mngt deployment, you do not need to do anything.**

On every startup, `api/main.py` runs `_seed_default_cluster()`. It reads `PF9_AUTH_URL` and `PF9_REGION_NAME` from your environment variables and inserts a `default` control plane + `default:<region_name>` region using `ON CONFLICT DO NOTHING`. For existing deployments this is a no-op after the first run. All existing resources (VMs, volumes, snapshots, etc.) are already tagged with the `default` region's ID via the schema migration that ran when you first upgraded to v1.73.0.

You will not see the Region Selector in the UI until you register a second region (the selector is hidden when only one region exists).

---

## 4. Adding a Control Plane

### Via the Admin UI (recommended)

1. Go to **Settings > Cluster Management** (superadmin-only tab)
2. Click **+ Add Control Plane**
3. Enter:
   - **Name** — a short slug used as a prefix for region names (e.g. `corp-dc2`)
   - **Auth URL** — the Keystone v3 endpoint (e.g. `https://pf9.your-cluster.example.com/keystone/v3`)
   - **Username / Password** — service account credentials (will be Fernet-encrypted at rest)
   - **Allow Private Network** — enable only if this control plane's auth URL is an RFC-1918 or loopback address (on-premises installations)
4. Click **Test Connection** — pf9-mngt performs a Keystone authentication and returns the token and service catalog summary without saving anything
5. Click **Save** — the control plane is persisted and immediately available for region registration

### Via the API

```http
POST /admin/control-planes
Authorization: Bearer <superadmin-token>
Content-Type: application/json

{
  "name": "corp-dc2",
  "auth_url": "https://pf9.your-cluster.example.com/keystone/v3",
  "username": "<service-account-username>",
  "password": "<service-account-password>",
  "user_domain_name": "Default",
  "project_name": "service",
  "project_domain_name": "Default"
}
```

Response includes the new `control_plane_id`. Store it for the region registration step.

### Test Without Saving

```http
POST /admin/control-planes/test
Content-Type: application/json

{ "auth_url": "...", "username": "...", "password": "..." }
```

Returns `{ "status": "ok", "regions": ["region-one", "eu-west-1"], "token_expires": "..." }` on success, or `{ "status": "auth_failed", "detail": "..." }` on failure.

---

## 5. Registering Regions

A **region** is one OpenStack availability zone within a control plane. You must register each region you want pf9-mngt to collect data from.

### Via the Admin UI

1. In **Cluster Management**, expand the control plane you just created
2. Click **Discover Regions** — pf9-mngt authenticates against Keystone and returns all regions found in the service catalog
3. Click **Register** next to each region you want to enable
4. Optionally set **Priority** (used for failover ordering) and **Latency Threshold** (ms)
5. The region is enabled immediately; the first sync begins within seconds

### Via the API

```http
POST /admin/control-planes/{cp_id}/regions
Authorization: Bearer <superadmin-token>

{
  "region_name": "eu-west-1",
  "priority": 1,
  "latency_threshold_ms": 500
}
```

### Disabling a Region

Disabled regions are excluded from all worker loops and API aggregations, but their historical data remains intact. Use `PATCH /admin/control-planes/{cp_id}/regions/{region_id}` with `{ "enabled": false }`.

---

## 6. The Region Selector UI

Once 2 or more regions are registered and enabled, a **Region Selector** dropdown appears in the top navigation bar (visible to superadmins and to users whose account is scoped to a region).

The dropdown:
- Groups options by control plane name
- Shows a live health-state colour dot next to each region:
  - **Green** — `healthy` (last sync succeeded, all API calls returned 200)
  - **Yellow** — `degraded` (last sync completed with errors; partial data available)
  - **Red** — `unreachable` (last sync failed with a network or timeout error)
  - **Grey** — `auth_failed` (credentials rejected; admin action required) or `unknown` (never synced)
- Has an **All Regions** option at the top that aggregates data across every enabled region

Changing the selection sets a `region_id` context in the React app (`ClusterContext`). All subsequent API calls from the UI automatically append `?region_id=<id>` to their requests. No page reload is needed.

**The Region Selector is hidden** when:
- Only one region is registered (single-cluster deployments are unaffected)
- The logged-in user is scoped to a specific region (their selector is pre-set and locked)

---

## 7. Cluster Management Admin Panel

Accessible from **Settings > Cluster Management** (superadmin only). Provides a full CRUD interface for the multi-cluster registry:

| Action | Description |
|---|---|
| Add Control Plane | Prompted form with connection test before save |
| Delete Control Plane | Cascades to all regions and clears `region_id` FK from orphaned resources |
| Test Control Plane | Re-runs Keystone auth and returns fresh service catalog |
| Discover Regions | Lists all regions in the service catalog, highlights which are already registered |
| Register Region | Creates a new `pf9_regions` row and begins initial sync |
| Enable / Disable Region | Toggles worker collection and UI visibility without data loss |
| Manual Sync | Triggers an immediate full sync for a selected region outside the normal worker schedule |
| View Sync Logs | Shows the last N `cluster_sync_metrics` rows per region: timestamp, duration, resource counts, errors |
| Edit Credentials | Re-encrypts and stores new password for a control plane |

---

## 8. Per-Region API Filtering

Every resource endpoint across all 7 API modules accepts an optional `?region_id=<uuid>` query parameter.

**Examples:**

```
GET /api/vms?region_id=<uuid>           -- VMs in one region only
GET /api/volumes                         -- volumes in ALL enabled regions
GET /api/snapshots?region_id=<uuid>      -- snapshots for one region
GET /api/metering/usage?region_id=<uuid> -- usage export scoped to one customer
GET /api/reports/snapshot-compliance     -- compliance across all regions (aggregated)
```

When `region_id` is omitted, the API returns data across all enabled regions. Callers can identify which region each row belongs to via the `region_id` field present on every resource response object.

### RBAC Enforcement

Users with a `region_id` assigned to their account (set by a superadmin) are automatically constrained — the API layer enforces this at the query level; passing a `region_id` that does not match the user's assigned region returns HTTP 403. Superadmin users may query any region.

---

## 9. Multi-Region Workers

All four background workers support parallel multi-region operation:

| Worker | Region behaviour |
|---|---|
| `metering_worker` | Collects CPU / memory / disk / network metrics per region; each `metering_data` row is tagged with `region_id` |
| `snapshot_worker` | Runs snapshot policies per region; `snapshot_runs` and `snapshot_records` carry `region_id` |
| `scheduler_worker` | Executes scheduled tasks (RVTools, drift checks) per region; merges results before writing |
| `search_worker` | Indexes resources per region; search queries filter or aggregate by `region_id` |

### Parallel Collection

On startup each worker calls `load_enabled_regions()` which queries `pf9_regions WHERE enabled = TRUE`. It then fans out with `asyncio.gather()` bounded by `asyncio.Semaphore(MAX_PARALLEL_REGIONS)` (default: 5). Each region task runs concurrently up to the semaphore limit.

### Timeout Isolation

Every per-region API call inside a worker is wrapped in `asyncio.wait_for(..., timeout=REGION_REQUEST_TIMEOUT_SEC)` (default: 30 s). If a region times out, the worker logs the failure, updates `pf9_regions.health_status = 'unreachable'`, and continues with the remaining regions. A slow or dead region cannot stall collection for healthy ones.

### Environment Variable Reference

| Variable | Default | Purpose |
|---|---|---|
| `MAX_PARALLEL_REGIONS` | `5` | Concurrency limit for fan-out across regions |
| `REGION_REQUEST_TIMEOUT_SEC` | `30` | Per-call asyncio timeout |
| `REGION_SYNC_INTERVAL_SEC` | `300` | How often the ClusterRegistry refreshes region health |

---

## 10. Region Health & Status Monitoring

`pf9_regions.health_status` is updated after every sync attempt. The values are:

| Status | Meaning | Worker behaviour |
|---|---|---|
| `healthy` | Last sync completed without errors | Normal collection |
| `degraded` | Last sync completed but some API calls returned errors | Collection continues; partial data written; alert raised |
| `unreachable` | Network error or timeout during last sync | Skipped in worker loops until next health check succeeds |
| `auth_failed` | Keystone returned 401 or 403 | Skipped; admin must fix credentials via Cluster Management |
| `unknown` | Never synced | Attempted on next worker cycle |

**Health recovery**: the worker retries unreachable regions on every cycle. When a previously unhealthy region responds successfully, `health_status` is automatically promoted back to `healthy`.

**Sync metrics** (`cluster_sync_metrics`) record, per run:
- `sync_duration_ms` — total wall-clock time for the full sync
- `resources_synced` — count of objects written
- `error_count` — number of failed API calls
- `avg_api_latency_ms` — average response time across Keystone calls in the run

These are visible in the Cluster Management admin panel (View Sync Logs) and are retained for 30 days by default.

---

## 11. Migration Planning with Registered Regions

As of **v1.77.0**, migration projects can be linked to registered control planes rather than using one-off ad-hoc connection details.

### Linking a Project to a Registered Region

When creating or editing a migration project in the Migration Planner:

1. Open the **Target Cluster** section
2. Switch from **Ad-hoc credentials** to **Registered region**
3. Select the target control plane and region from the dropdowns — only regions with `health_status = 'healthy'` are shown
4. Save — the project now stores `target_region_id` (and `source_region_id` for cross-cluster analysis)

### PCD Gap Analysis with Registered Regions

The **pcd-gap-analysis** wizard (`POST /api/migration/pcd-gap-analysis`) detects the `target_region_id` on the project:
- If set: uses the ClusterRegistry client for that region (already authenticated, session reused, SSRF guard applied)
- If not set: falls back to the ad-hoc Nova/Glance credentials embedded in the project (backward compatible)

The analysis compares source and target Nova flavours, Glance images, network topologies, and security groups, producing a compatibility matrix that indicates which VMs can migrate directly and which require remapping.

### Cross-Region Migration Workflow

```
1. Register source cluster (may already be your "default" region)
2. Register target cluster (new control plane + region)
3. Create migration project => link both regions
4. Run pcd-gap-analysis => review compatibility matrix
5. Build migration waves in the Planner
6. Execute migration waves (VM live-migration via Nova API on each cluster)
```

---

## 12. Cross-Region Task Bus

`cluster_tasks` is a database-backed state machine for long-running cross-region operations. It exists now as infrastructure; the full orchestration layer is under active development.

### Current State

- Table exists: `cluster_tasks` with columns `task_type`, `operation_scope`, `source_region_id`, `target_region_id`, `replication_mode`, `state`, retry fields, and a `payload` JSONB
- `GET /admin/control-planes/cluster-tasks` — superadmin endpoint returns all tasks with current state
- Worker safety: `FOR UPDATE SKIP LOCKED` prevents double-execution when multiple worker replicas run
- Snapshot replication (`task_type = 'snapshot_replication'`) and DR failover (`task_type = 'dr_failover'`) are defined but the execution processors are deferred pending a second-region test environment

### Planned Operations

| Task Type | Trigger | Description |
|---|---|---|
| `snapshot_replication` | Policy or admin action | Copy snapshots from `source_region_id` to `target_region_id` on a schedule |
| `dr_failover` | Manual or automated | Promote replicated snapshots to running VMs in the target region |
| `cross_region_migration` | Migration Planner | Orchestrate multi-wave VM migration across regions |

---

## 13. Security

### Credential Encryption

Control plane passwords are encrypted with **Fernet** (AES-128-CBC with HMAC-SHA256 authentication) before being written to `pf9_control_planes.password_enc`. The Fernet key is stored in `FERNET_KEY` (environment variable / secrets mount) and never written to the database. To rotate keys, decrypt all stored credentials, generate a new key, re-encrypt, and restart.

### SSRF Protection

`pf9_control_planes.allow_private_network` defaults to `FALSE`. When false, the `auth_url` for a control plane is validated against RFC-1918 (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) and loopback (`127.0.0.0/8`, `::1`) address ranges before any outbound connection is made. This prevents an attacker with admin access from using pf9-mngt as an SSRF proxy to reach internal services.

To register a control plane whose auth URL is a private IP address (on-premises deployment), a superadmin must explicitly set `allow_private_network: true` through the API.

### RBAC

Cluster Management endpoints (`/admin/control-planes/*`) require `role = superadmin`. Regular admin users can query resources with `?region_id=` but cannot modify the registry. Region-scoped users are locked to their assigned region at the query layer — no `?region_id=` override is accepted.

### Audit Trail

All control plane and region CRUD operations are written to the `activity_log` table with `user_id`, `action`, `resource_type = 'cluster_registry'`, and full `before`/`after` JSONB snapshots of changed fields. Passwords are redacted before the snapshot is stored.

---

## 14. API Reference

All endpoints require a valid JWT. Cluster Management endpoints require `role = superadmin`.

### Control Planes

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/control-planes` | List all registered control planes |
| `POST` | `/admin/control-planes` | Create a new control plane |
| `GET` | `/admin/control-planes/{id}` | Get one control plane (password field omitted) |
| `PATCH` | `/admin/control-planes/{id}` | Update name, credentials, `allow_private_network` |
| `DELETE` | `/admin/control-planes/{id}` | Delete control plane and cascade to regions |
| `POST` | `/admin/control-planes/test` | Test connection without saving |

### Regions

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/control-planes/{cp_id}/regions` | List all regions for a control plane |
| `POST` | `/admin/control-planes/{cp_id}/regions` | Register a new region |
| `GET` | `/admin/control-planes/{cp_id}/regions/{id}` | Get one region with sync metrics |
| `PATCH` | `/admin/control-planes/{cp_id}/regions/{id}` | Update priority, enabled, latency threshold |
| `DELETE` | `/admin/control-planes/{cp_id}/regions/{id}` | Remove a region from the registry |
| `POST` | `/admin/control-planes/{cp_id}/regions/discover` | Auto-discover regions from Keystone service catalog |
| `POST` | `/admin/control-planes/{cp_id}/regions/{id}/sync` | Trigger an immediate manual sync |

### Global

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/control-planes/cluster-tasks` | List cluster_tasks with current state |
| `GET` | `/admin/control-planes/health` | Summary health status across all regions |

### Payload Reference: Create Control Plane

```json
{
  "name": "corp-dc2",
  "auth_url": "https://pf9.your-cluster.example.com/keystone/v3",
  "username": "<service-account-username>",
  "password": "<service-account-password>",
  "user_domain_name": "Default",
  "project_name": "service",
  "project_domain_name": "Default",
  "allow_private_network": false
}
```

### Payload Reference: Create Region

```json
{
  "region_name": "eu-west-1",
  "priority": 1,
  "latency_threshold_ms": 500,
  "enabled": true
}
```

---

## 15. Troubleshooting

### Region shows `auth_failed`

The service account credentials stored for that control plane are invalid. Either the password was rotated, or the account was disabled.

**Fix**: In Cluster Management, click **Edit Credentials** for the affected control plane, enter the new password, and click **Test** to verify before saving.

### Region shows `unreachable`

pf9-mngt cannot reach the Keystone endpoint for that region. Common causes:
- Network firewall or ACL change
- Auth URL changed
- PF9 platform is down or under maintenance

**Debug**:
```bash
curl -k -s https://<auth_url>/keystone/v3
```
If the endpoint returns a 200 with a `{"version": ...}` payload, the platform is reachable. If not, check the network path from the Docker host. 

**Check recent sync errors:**
```http
GET /admin/control-planes/{cp_id}/regions/{region_id}
```
The response includes `last_error` (the exception message from the last failed sync) and `last_sync_at`.

### Region shows `degraded`

Some API calls during the last sync returned errors. Common causes:
- One or more OpenStack services (Nova, Neutron, etc.) are returning 5xx responses
- Quota or rate limiting applied to the service account
- Service catalog endpoint URL is wrong for one service

**Debug**: View sync logs in the Cluster Management panel for the affected region. The `error_count` and per-service breakdown will identify the failing service.

### Region Selector not visible

The Region Selector is hidden if:
1. Only one region is registered (or all others are disabled)
2. The logged-in user's role does not include multi-region access

**Fix**: Register and enable at least one additional region. The selector appears automatically without a restart.

### `allow_private_network` SSRF error

You are trying to register a control plane with a private IP auth URL and the SSRF guard is blocking it.

**Fix**: Set `allow_private_network: true` when creating the control plane via the API, or enable it in the Edit Credentials dialog in the admin UI. Only available to superadmins.

### Old resources still show `region_id = NULL`

Resources created before v1.73.0 were backfilled to the `default` region during the schema migration. If you see `NULL` values, the migration may not have run.

**Fix**:
```bash
docker exec pf9_api python run_migration.py
```
Or manually:
```sql
UPDATE vms SET region_id = (SELECT id FROM pf9_regions WHERE region_name = 'default:region-one' LIMIT 1) WHERE region_id IS NULL;
-- Repeat for volumes, networks, security_groups, etc.
```

### worker not collecting from a new region

Workers load the region list on startup. If you registered a new region while the worker was running, it may not pick it up until the next collection cycle (or restart).

**Fix**: The workers call `load_enabled_regions()` at the start of each collection cycle, so the new region will be included in the next run automatically. If you need it immediately, restart the affected worker:
```bash
docker restart pf9_metering_worker
docker restart pf9_scheduler_worker
```
