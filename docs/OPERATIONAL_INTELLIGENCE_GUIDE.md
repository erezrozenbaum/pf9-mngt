# Operational Intelligence Guide

> **Audience**: MSP operators, NOC engineers, account managers, and MSP executives using OpsAnchor.  
> **Scope**: End-to-end guide to every intelligence feature — from reading the insight feed to generating a QBR PDF and monitoring tenant health through the observer portal.

---

## Table of Contents

1. [What Is Operational Intelligence?](#what-is-operational-intelligence)
2. [The Insight Feed](#the-insight-feed)
3. [Department Workspaces](#department-workspaces)
4. [Insight Detail and Recommendations](#insight-detail-and-recommendations)
5. [SLA Tracking and Commitments](#sla-tracking-and-commitments)
6. [Capacity Forecasting](#capacity-forecasting)
7. [Cross-Region and Anomaly Detection](#cross-region-and-anomaly-detection)
8. [Revenue Leakage Detection](#revenue-leakage-detection)
9. [Quarterly Business Review (QBR) Reports](#quarterly-business-review-qbr-reports)
10. [PSA Webhook Integration](#psa-webhook-integration)
11. [Tenant Health and the Observer Portal](#tenant-health-and-the-observer-portal)
12. [Intelligence Settings](#intelligence-settings)
13. [Copilot Integration](#copilot-integration)
14. [Role-Based Dashboard Views](#role-based-dashboard-views)

---

## What Is Operational Intelligence?

Operational Intelligence is the layer of OpsAnchor that watches your infrastructure continuously and tells you what matters — before clients call to report it.

It works in the background by:
- **Detecting** patterns in your infrastructure inventory (resource utilisation, quota trends, configuration drift, SLA compliance, billing against contracts).
- **Classifying** each finding as a typed insight with a severity level (`critical`, `high`, `medium`, `low`).
- **Surfacing** insights in a unified feed, sorted by risk, so the right person sees the right thing when they open the app.
- **Recommending** concrete actions and pre-staging runbooks ready to execute.

The system produces no alerts that require a human to manually tune thresholds. All detection logic is threshold-plus-trend based: it compares current state against what is expected given recent history. Findings expire automatically when the underlying condition resolves.

---

## The Insight Feed

**Location**: Intelligence → Insights tab  
**Refresh**: Background worker runs every 15 minutes. The feed auto-refreshes on tab focus.

### Reading the feed

Each row in the feed represents one active finding:

| Column | What it tells you |
|--------|------------------|
| **Severity badge** | `CRITICAL` (red), `HIGH` (orange), `MEDIUM` (yellow), `LOW` (grey) |
| **Type** | The category of finding (see types below) |
| **Tenant** | Which client the finding is about |
| **Title** | One-line summary — e.g. *"vCPU quota at 84% — forecast: 90% in 8 days"* |
| **Detected** | When the finding was first created |
| **Status** | `open` (unacknowledged), `acknowledged`, `resolved` |

### Insight types

| Type | What it detects | Default workspace |
|------|----------------|-------------------|
| `capacity` | Quota utilisation trending toward the limit | Engineering |
| `capacity_storage` | Block storage quota near the limit | Engineering |
| `capacity_compute` | vCPU or RAM quota near the limit | Engineering |
| `capacity_quota` | Any quota type above the warning threshold | Engineering |
| `waste` | Idle VMs, unattached volumes, old snapshots | Engineering |
| `anomaly` | Usage spike deviating from recent baseline | Engineering |
| `cross_region` | Unbalanced resource distribution across regions | Engineering |
| `drift` | Configuration change since last known-good state | Support |
| `snapshot` | Snapshot policy violation or age breach | Support |
| `incident` | Critical service impact affecting a tenant | Support |
| `risk` | Health score declining or coverage gap | Operations + Support |
| `health` | Tenant health score below acceptable threshold | Operations |
| `sla_risk` | SLA commitment at risk of breach this period | Operations + Support |
| `leakage` | Tenant consuming beyond contracted limits | Operations |

### Filtering and sorting

- **Severity filter**: Click severity buttons in the toolbar to show only findings above a threshold.
- **Status filter**: Show `open`, `acknowledged`, or all.
- **Sort**: Click any column header. Default sort is severity descending, then detection time.
- **Search**: The Ops Search bar at the top of the app searches across all insight titles and tenant names.

### Acknowledging and resolving

- **Acknowledge**: Marks the finding as seen. It stays in the feed but is visually de-emphasised. Use this when you are aware of the issue and tracking it.
- **Resolve**: Marks the finding as closed. Use only when the underlying problem is fixed — the worker will re-open it if conditions regress.
- Both actions are available on the detail drawer (click any row) and via the bulk-action toolbar when multiple rows are selected.

---

## Department Workspaces

The workspace selector (Support / Engineering / Operations / Global) is a pre-configured filter that shows you the slice of the feed most relevant to your role.

| Workspace | What you see | Who uses it |
|-----------|-------------|-------------|
| **Support** | Drift, incidents, snapshot violations, SLA risks | Client-facing support engineers |
| **Engineering** | Capacity, waste, anomaly, cross-region | Infrastructure engineers, NOC |
| **Operations** | SLA risk, health decline, leakage, revenue gaps | Operations managers, billing |
| **Global** | All insight types, no filter | Admins, leads, cross-functional review |

Your workspace selection is saved in browser `localStorage` under `pf9_intelligence_workspace`. It persists across sessions on the same browser.

**Default workspace by role**: Users with the `operator` role default to Engineering. All other roles default to Global.

Changing workspace does not lose your severity or status filters — they stack on top of the workspace type filter.

---

## Insight Detail and Recommendations

Click any row in the feed to open the detail drawer on the right.

### Detail drawer contents

- **Full title and description**: Plain-language explanation of the finding, including the specific metric and threshold that triggered it.
- **Affected resource**: The tenant, project, region, or VM/volume the finding relates to. Where applicable, a link to the resource's detail page.
- **Metric trend**: The raw numbers that generated the insight (e.g. vCPU quota used / total, days until projected breach).
- **Timeline**: When the insight was first detected, last updated, and current status.

### Recommendations panel

Below the detail section is a list of recommended actions — pre-staged runbook steps generated by the recommendation engine at detection time.

Each recommendation has:
- A plain-language description of what to do and why.
- Confidence level (`high`, `medium`, `low`) based on how closely the current state matches known patterns.
- An **Apply** button that opens the linked runbook pre-filled with the affected resource details.

Recommendations are suggestions, not automatic actions. A human must review and approve before any runbook executes.

---

## SLA Tracking and Commitments

**Location**: Intelligence → Tenant Health → SLA tab (in the tenant detail drawer)

### What SLA tracking covers

- **Commitments**: Per-tenant SLA targets you have agreed to (e.g. MTTR ≤ 4 hours, snapshot frequency ≤ 48 hours, uptime ≥ 99.5%).
- **Compliance status**: Whether each commitment is currently being met, based on operational data.
- **Breach risk**: When a commitment is trending toward failure before the month closes, an `sla_risk` insight is raised in the Operations and Support workspaces.

### Viewing a tenant's SLA status

1. Open **Tenant Health** from the navigation.
2. Click a tenant row to open the detail drawer.
3. Select the **SLA** tab. You will see two sub-tabs:
   - **Commitments**: The current targets and their live compliance status.
   - **History**: Month-by-month compliance record for each commitment type.

The history table highlights breach months in red and at-risk months in amber for quick scanning.

### Editing SLA commitments

From the **Commitments** sub-tab:
- Click **Edit Commitments** to open the inline editor.
- Adjust target values for any commitment type.
- Save. The compliance worker recalculates at its next run (up to 15 minutes).

Requires `admin` or `superadmin` role.

### SLA compliance insights

When a commitment is on track: no insight is raised.  
When a commitment is at risk (current trend will breach by end of period): `sla_risk` insight raised, severity `high`.  
When a commitment has already been breached: insight severity escalates to `critical` and an `sla_risk` row appears in both Operations and Support workspaces.

---

## Capacity Forecasting

The capacity engine runs on every inventory collection cycle and produces both current-state and forward-looking insights.

### What is forecast

- **vCPU quota**: Current usage + 30-day linear trend. Forecast date when quota will hit 90%.
- **RAM quota**: Same method.
- **Block storage quota**: Current Cinder volume usage vs. quota, trended forward.
- **VM count quota**: Instance count vs. quota limit.

### Reading a capacity insight

A typical capacity insight title: *"vCPU quota at 84% — forecast: 90% in 8 days"*

This means the tenant is currently at 84% utilisation, and at the current growth rate will hit the 90% warning threshold in 8 days. The insight severity scales with the projected days-to-breach:

| Days to breach | Severity |
|----------------|----------|
| > 30 | LOW |
| 15–30 | MEDIUM |
| 7–14 | HIGH |
| < 7 | CRITICAL |

### Acting on capacity insights

The recommendation engine suggests two typical actions:
1. **Raise quota**: Open the quota management runbook for this tenant and project.
2. **Identify waste**: Cross-reference with `waste` type insights — if the tenant has idle VMs, reclaiming them buys time before a quota increase is needed.

---

## Cross-Region and Anomaly Detection

These two insight types are generated by Phase 3 engines and appear in the **Engineering** workspace.

### Cross-region imbalance

If a single region is hosting significantly more workload than the others (relative to available capacity), a `cross_region` insight flags it. This is an early warning that one region is becoming a concentration risk before it hits quota limits.

### Anomaly detection

The anomaly engine compares this week's resource usage pattern to the previous 4-week baseline for each tenant. A significant deviation (above 2 standard deviations from baseline) generates an `anomaly` insight.

Common triggers:
- Sudden VM proliferation (misconfigured autoscaling, test environment left running).
- Large volume creation event outside normal provisioning windows.
- Snapshot frequency spike (runaway backup policy).

Anomaly insights are informational by default (severity `medium`). They are not recommendations to act — they are prompts to investigate whether the change was intentional.

---

## Revenue Leakage Detection

**Location**: Operations workspace, type `leakage`

### What it detects

Leakage occurs when a tenant's actual resource consumption exceeds what their MSP contract entitles them to. OpsAnchor compares:
- **Contracted resource limits** stored in the contract entitlements registry (`msp_contract_entitlements`).
- **Actual consumption** from the live inventory (project quotas in use).

When consumption exceeds contracted limits, a `leakage` insight is raised identifying the tenant, resource type, and overage percentage.

### Leakage severities

| Overage | Severity |
|---------|----------|
| < 5% over contracted | LOW |
| 5–15% over | MEDIUM |
| 15–30% over | HIGH |
| > 30% over | CRITICAL |

### Ghost resources

A separate leakage signal called "ghost resources" identifies resources that exist in the platform but have no corresponding contract entry at all. This means the MSP is providing resources with no billing coverage.

Ghost resource insights appear with type `leakage` and include "ghost" in the title.

### Acting on leakage insights

Typical actions:
- **Update the contract**: Open the contract entitlements view and increase the contracted limit, then issue a revised invoice.
- **Reclaim the resource**: If the over-consumption is unauthorized or accidental, open the resource management runbook to deprovision.
- **QBR inclusion**: Leakage findings are automatically included in the next QBR report for this tenant (see below).

---

## Quarterly Business Review (QBR) Reports

**Location**: Tenant Health detail drawer → **Business Review** button

A QBR is a PDF document generated on demand that summarises the service delivery record for a specific tenant over a selected period.

### Report contents

- **Executive summary**: SLA compliance rate, open/closed incidents, MTTR average.
- **Capacity trends**: Quota utilisation month by month, capacity runway.
- **Waste identified**: Resources flagged as idle or underutilised; estimated recovery value.
- **Revenue leakage**: Over-consumption events and their financial impact (requires labor rate configuration).
- **Recommendations executed**: Runbook actions taken during the period and their outcomes.
- **Upcoming risks**: Any currently open insights that may affect the next period.

### Generating a QBR

1. Open **Tenant Health** and click the tenant.
2. Click **Business Review** in the drawer header.
3. Select the period (defaults to current month, can be set to any calendar month).
4. Click **Generate**. The PDF is built server-side and downloads automatically.

### Labor rate configuration

For the waste and leakage sections to show dollar-value figures, configure your standard labor rates in **Intelligence Settings** (see below). Without labor rates, the report shows only resource counts and percentages.

---

## PSA Webhook Integration

**Location**: Intelligence Settings → PSA Webhooks

OpsAnchor can push insight events to your Professional Services Automation (PSA) tool (e.g. Zendesk, ServiceNow, ConnectWise) automatically when an insight is created or severity-escalated.

### Setting up a webhook

1. Go to **Intelligence Settings → PSA Webhooks**.
2. Click **Add Webhook**.
3. Enter:
   - **URL**: Your PSA ticket creation endpoint.
   - **Auth header**: Bearer token or API key (stored encrypted).
   - **Trigger**: Choose whether to fire on `new_insight`, `severity_escalation`, or both.
   - **Severity threshold**: Only fire for insights at or above this severity (e.g. `high`).
4. **Test** the connection using the **Send Test Event** button.
5. Save.

### Webhook payload

```json
{
  "event": "new_insight",
  "insight_id": 1042,
  "insight_type": "sla_risk",
  "severity": "critical",
  "tenant_name": "Acme Corp",
  "title": "SLA MTTR commitment at risk — 2 critical incidents open",
  "detected_at": "2026-04-22T09:15:00Z",
  "recommendation_count": 2,
  "source": "opsanchor"
}
```

The PSA integration is outbound only. Closing a ticket in your PSA does not automatically resolve the insight. Use the **Resolve** action in the feed to close the finding on the OpsAnchor side.

---

## Tenant Health and the Observer Portal

### Tenant health scores

**Location**: Navigation → Tenant Health

The Tenant Health view shows every tenant ranked by composite health score. The score is computed from three dimensions:

| Dimension | What it measures |
|-----------|-----------------|
| **Efficiency** | Resource utilisation vs. waste — how well the tenant uses what they have |
| **Stability** | Incident frequency, drift rate, SLA compliance trend |
| **Capacity Runway** | Days until projected quota breach across all resource types |

The three-dial display in the tenant portal (see below) reflects these same three dimensions in a client-friendly format.

### Opening tenant detail

Click any row to open the detail drawer. The drawer contains:
- **Overview**: Health score breakdown, top open insights.
- **Resources**: Live VM, volume, and network inventory for this tenant.
- **SLA**: Commitments and compliance history.
- **Portal**: Tenant portal user management (invite observers, set roles).

### Observer Portal

The Observer Portal is a separate read-only web application (`/tenant`) that clients can access to view their own service health — without needing an admin account.

**Portal features**:
- Three health dials: Efficiency, Stability, Capacity Runway.
- List of open insights (read-only, no acknowledge/resolve).
- SLA compliance status for the current period.
- Historical health trend graph.

**Inviting a client**

1. Open the tenant detail drawer and go to the **Portal** sub-tab.
2. Click **Invite User**.
3. Enter the client's email address and select a role:
   - **Manager**: Can see all health data including revenue leakage and SLA details.
   - **Observer**: Can see health dials and open insights only.
4. An invitation email is sent. The client sets their own password on first login.

**Portal user management**

From the **Portal** sub-tab you can:
- View all active portal users for this tenant.
- Change a user's role (manager ↔ observer).
- Revoke access (deactivate account).

Only users with `admin` or `superadmin` role in OpsAnchor can manage portal users.

---

## Intelligence Settings

**Location**: Navigation → Intelligence Settings (admin-only)

### Labor rates

Configure the hourly rates used to calculate dollar-value estimates in QBR reports and waste calculations.

| Rate type | Used for |
|-----------|----------|
| **Tier 1 labor** | Basic support and monitoring hours |
| **Tier 2 labor** | Escalated incidents and configuration changes |
| **Engineering** | Infrastructure provisioning and optimization work |

Rates are stored per-tenant (override) with a global default fallback.

### PSA webhooks

See [PSA Webhook Integration](#psa-webhook-integration).

### Contract entitlements (CSV import)

If you have existing contract data in a spreadsheet, you can bulk-import it via the CSV import function in Intelligence Settings. The import format is documented in the upload dialog tooltip.

### Threshold overrides

The default thresholds for capacity warnings (90% quota → HIGH, 95% → CRITICAL) and waste detection (VM idle for 7 days) can be adjusted per-tenant. Contact your OpsAnchor administrator to configure tenant-specific overrides.

---

## Copilot Integration

The OpsAnchor Copilot understands your intelligence context. You can use natural-language queries to interrogate the insight feed and get operational guidance.

### Supported Copilot intents

| Query example | What Copilot does |
|--------------|-------------------|
| "Show me critical insights for Acme Corp" | Filters the feed by tenant and severity |
| "What is at risk this week?" | Returns all HIGH+ insights created in the last 7 days |
| "Summarise capacity issues across all tenants" | Groups capacity insights by tenant with a plain-language summary |
| "Which tenants are approaching their SLA breach?" | Lists all `sla_risk` insights sorted by urgency |
| "Acknowledge all low-severity waste insights" | Bulk-acknowledges matching insights after confirmation |

Copilot responses always show the source insight IDs so you can verify the underlying data.

---

## Role-Based Dashboard Views

Users are automatically routed to a dashboard tailored to their role on login. The destination is controlled by the **Account Management** or **Executive Leadership** department assignment in the admin panel.

### NOC Engineers and Operators

Land on the main **Dashboard** then navigate to **Insights** from the sidebar. The Insights feed is pre-filtered to show only open/active items.

### Account Managers

Land directly on **My Portfolio** — a per-tenant portfolio table showing every client with:

```
Client         SLA Status     Contract Usage   Open Criticals   Leakage Alerts
──────────────────────────────────────────────────────────────────────────────
Acme Corp      ⚠ AT RISK      94% vCPU         2                1
Initech        🚨 BREACHED    112% vCPU        5                3
GlobalTech     ✅ OK          61% vCPU         0                0
```

Filter by status (All / OK / At Risk / Breached / Not Configured) or search by client name. The KPI strip at the top shows aggregate counts for fast triage.

### MSP Executives

Land on **Portfolio Health** — a fleet-wide executive summary with six KPI cards:

- **Fleet Health %** — percentage of clients meeting SLA commitments
- **SLA Breached** — count requiring immediate action
- **SLA At Risk** — count approaching breach threshold
- **Open Critical Issues** — sum across all clients
- **Est. Revenue Leakage** — monthly dollar estimate (requires contract unit prices configured)
- **Avg MTTR** — fleet mean time-to-recover vs contracted commitment

A stacked health bar at the top shows the proportion of clients in each SLA state at a glance.

> **Revenue leakage dollar amounts** are computed from `contracted × unit_price × overage_pct`. If no `unit_price` is set on contract entitlements (Admin → Intelligence Settings → Contract Entitlements), the card shows `—` with a prompt to configure pricing.

---

## Quick Reference

### Key keyboard shortcuts

| Action | Shortcut |
|--------|----------|
| Open Ops Search | `Ctrl + K` / `Cmd + K` |
| Acknowledge selected insight | `A` (with row selected) |
| Resolve selected insight | `R` (with row selected) |
| Switch to next workspace | `Tab` (in workspace selector) |

### Insight lifecycle

```
Detected (open)
    ↓
Acknowledged   ←  (human reviews, marks seen)
    ↓
Resolved       ←  (problem fixed; or auto-resolved when condition clears)
```

If a resolved insight's underlying condition returns, it is automatically re-opened with a new detection timestamp.

### Support resources

- [Runbooks documentation](TICKET_GUIDE.md) — how to approve and execute runbook recommendations.
- [Tenant Portal Guide](TENANT_PORTAL_GUIDE.md) — full observer portal setup and usage.
- [Admin Guide](ADMIN_GUIDE.md) — user management, role assignment, system configuration.
- [API Reference](API_REFERENCE.md) — intelligence API endpoints for integrations.
