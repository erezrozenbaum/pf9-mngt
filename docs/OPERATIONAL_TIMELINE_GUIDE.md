# Operational Event Timeline — Guide

**Feature codename**: `operational-timeline`  
**Available since**: v1.96.0  
**Stable release**: v1.96.8

---

## Overview

The Operational Event Timeline is a unified, chronological audit trail of every significant infrastructure event — harvested automatically from 10 source tables and made available to admins and tenants through dedicated UI tabs, REST APIs, and Copilot intents.

Events cover: monitoring alerts, provisioning actions, backup/snapshot outcomes, SLA state changes, ticket activity, auth events, metering anomalies, and AI-generated insights.

---

## Event Schema

| Column | Type | Description |
|---|---|---|
| `id` | UUID | Unique event identifier |
| `occurred_at` | timestamptz | When the event occurred (indexed) |
| `recorded_at` | timestamptz | When it was harvested (auto-set) |
| `domain_id` | UUID | Owning tenant domain (NULL = global) |
| `domain_name` | text | Denormalized domain name |
| `entity_type` | text | `vm`, `host`, `tenant`, `ticket`, `backup`, `snapshot`, `sla`, `runbook` |
| `entity_id` | text | ID of the affected resource |
| `entity_name` | text | Human-readable name of the resource |
| `category` | text | See categories below |
| `severity` | text | `info`, `warning`, `critical` |
| `source` | text | Source table the event was harvested from |
| `title` | text | Short, human-readable event title |
| `description` | text | Full event detail |
| `actor` | text | User, system, or service that triggered the event |
| `metadata` | jsonb | Source-specific extra fields |

### Event Categories

| Category | Source | Description |
|---|---|---|
| `monitoring` | `operational_insights` | Threshold alerts, anomalies detected |
| `provisioning` | `activity_log`, `vm_provisioning_batches` | VM create/delete/modify actions |
| `snapshot` | `snapshot_records` | Snapshot created, deleted, policy executed |
| `backup` | `backup_history` | Backup started, completed, failed |
| `sla` | `sla_compliance_monthly` | SLA period opened/closed, breach detected |
| `ticket` | `support_tickets` | Ticket opened, updated, resolved |
| `intelligence` | `operational_insights` | AI insight opened or resolved |
| `auth` | `auth_audit_log` | Login, logout, failed auth attempt |
| `metering` | `metering_efficiency` | Efficiency score change, quota threshold hit |
| `runbook` | `runbook_executions` | Runbook triggered, completed, failed |

### Severity Levels

| Severity | Meaning |
|---|---|
| `info` | Normal operational event — no action required |
| `warning` | Potential issue — monitor or investigate |
| `critical` | Active problem — immediate action recommended |

---

## Accessing the Timeline (Admin)

### Via the Admin UI

1. Navigate to **Intelligence** → **Timeline** tab.
2. Select a **mode**:
   - **Tenant** — full event chain for a selected domain (use the tenant dropdown)
   - **Resource** — events for a specific entity type + ID
   - **Global** — rolling cross-region feed visible only to admins
3. Apply filters: **time range** (2h / 6h / 24h / 7d / 30d), **severity**, **category chips**, or **free-text search**.
4. Events display newest-first with category color stripes, severity badges, entity/domain chips, and expand-to-detail for description and metadata.

### Via the REST API

```
GET /api/timeline
```

Key query parameters:

| Parameter | Example | Description |
|---|---|---|
| `domain_id` | `?domain_id=<uuid>` | Filter to a specific tenant |
| `entity_type` | `?entity_type=vm` | Filter by entity type |
| `entity_id` | `?entity_id=<uuid>` | Events for one resource |
| `severity` | `?severity=critical` | Filter by severity |
| `category` | `?category=provisioning` | Filter by category |
| `from_time` | `?from_time=2026-05-01T00:00:00Z` | Start of time window |
| `to_time` | `?to_time=2026-05-13T23:59:59Z` | End of time window |
| `search` | `?search=failed` | Free-text search on `title` |
| `limit` / `offset` | `?limit=50&offset=0` | Pagination |

#### Correlated events (blast-radius)

```
GET /api/timeline/correlated?entity_type=vm&entity_id=<uuid>&minutes=120
```

Returns all events within ±N minutes of the most recent event for the given entity — useful for root-cause analysis.

#### Stats summary

```
GET /api/timeline/stats?domain_id=<uuid>&hours=24
```

Returns event counts grouped by category and severity for the given time window.

---

## Accessing the Timeline (Tenant Portal)

Tenant users access their domain-scoped event history under **⏱ Event History** in the self-service portal.

- **Server-side enforced**: all events are filtered to the authenticated tenant's `domain_id` — cross-tenant access is not possible.
- **Endpoints**: `GET /tenant/timeline` (paginated) · `GET /tenant/timeline/stats`
- **Filters**: time range picker, 7 category chips, severity filter, free-text search on event title.

---

## Copilot Intents (v1.96.7)

Three built-in Copilot intents query the timeline:

| Trigger phrase | Intent key | What it returns |
|---|---|---|
| "what changed before the incident?" / "why did X fail?" | `timeline_what_changed` | Last 10 warning/critical events in the past 6 hours |
| "show me [tenant] timeline" | `timeline_tenant` | Last 25 events for the named domain |
| "what happened in the last N hours?" | `timeline_recent_hours` | Global event feed for the past N hours (default 24h) |

The LLM context (injected into every Copilot system prompt) also includes the 5 most recent `warning`/`critical` events, enabling the AI to reason about recent infrastructure state even for general questions.

**Example queries**:
```
What changed before the last SLA breach?
Show me ORG1 timeline
What happened in the last 6 hours?
Why did the last backup fail?
```

---

## Contextual Navigation Hooks

| Starting point | Hook | Action |
|---|---|---|
| Dependency Graph node | "⏱ Show Timeline" in node sidebar | Opens Timeline pre-filtered to that resource |
| Intelligence insight row | "⏱ Preceding" button | Opens Timeline pre-filtered to insight entity |
| Support ticket detail | "Correlated events (±1h)" section | Shows events within ±1 hour of ticket creation |

---

## Event Harvester

The `TimelineHarvester` runs inside the **intelligence worker** on every cycle (default: every 5 minutes).

- **Source tables**: `activity_log`, `operational_insights`, `support_tickets`, `backup_history`, `snapshot_records`, `sla_compliance_monthly`, `runbook_executions`, `metering_efficiency`, `metering_quotas`, `auth_audit_log`
- **Cursor tracking**: positions stored in `timeline_harvest_cursors` — fully idempotent, resumable after restarts
- **Domain resolution**: every harvested event resolves `domain_id` via JOINs to the owning domain
- **Retention pruning**: events older than `TIMELINE_RETENTION_DAYS` (default: 180) are pruned automatically after each cycle

To check harvester status:

```powershell
kubectl logs -n pf9-mngt -l app=pf9-intelligence-worker --tail=50 | Select-String "TimelineHarvester|timeline"
```

---

## RBAC and Visibility

| Role | Can see |
|---|---|
| `superadmin`, `admin` | All events (global + all tenants) |
| `operator`, `viewer` | All events (global + all tenants) |
| `tenant` (portal) | Own domain only — server-side enforced via JWT `domain_id` claim |

---

## Retention Policy

Default retention: **180 days** (`TIMELINE_RETENTION_DAYS` environment variable).

To change:
```yaml
# k8s/helm/pf9-mngt/values.yaml
intelligence_worker:
  env:
    TIMELINE_RETENTION_DAYS: "365"
```

---

## Version History

| Version | What was added |
|---|---|
| v1.96.0 | DB schema: `operational_events`, `timeline_harvest_cursors`, nav seed |
| v1.96.1 | API: `GET /api/timeline`, `GET /api/timeline/correlated`, `GET /api/timeline/stats` |
| v1.96.2 | Intelligence worker: `TimelineHarvester`, all 10 source harvesters, pruning |
| v1.96.3 | Admin UI: `OperationalTimelineTab` — Tenant / Resource / Global modes |
| v1.96.4 | Contextual hooks: Dependency Graph, Insights, Tickets |
| v1.96.5 | Tenant portal: `GET /tenant/timeline`, `GET /tenant/timeline/stats`, `TenantTimeline.tsx` |
| v1.96.6 | Bugfix: `domain_id` NULL → resolved via JOINs; `tenant_portal_role` GRANT; field name corrections |
| v1.96.7 | Copilot: 3 timeline intents, LLM context injection, suggestion chips |
| v1.96.8 | Column name fix (`occurred_at`); this guide; `ADMIN_GUIDE.md` and `API_REFERENCE.md` updated |
