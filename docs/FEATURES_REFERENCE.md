# Features Reference — Technical Deep Dive

> Complete technical reference for all pf9-mngt features.
> For a high-level overview and quick start see [README.md](../README.md).

---

## 🌟 Key Features — Technical Reference

### 🔐 Enterprise Authentication & Authorization
- **LDAP Integration**: Production-ready OpenLDAP authentication — also compatible with Active Directory
- **Role-Based Access Control**: 5-tier permission system (Viewer, Operator, Admin, Superadmin, Technical)
- **MFA Support**: TOTP-based two-factor authentication (Google Authenticator compatible) with backup recovery codes
- **JWT Token Management**: Secure 480-minute sessions with Bearer token authentication
- **RBAC Middleware**: Automatic permission enforcement on all resource endpoints
- **Audit Logging**: Complete authentication event tracking — login, logout, failed attempts, user management
- **System Audit**: 90-day retention with filtering by user, action, date range, and IP address

### 📊 RVTools-Style Unified Inventory
- **29 Resource Types**: Domains, Projects, Users, VMs, Volumes, Snapshots, Networks, Subnets, Ports, Floating IPs, Routers, Security Groups, Hypervisors, Flavors, Images, Roles, Role Assignments, Groups, Snapshot Policies, and operational event types
- **Human-Friendly Names**: UUID-to-name resolution across all resource types
- **Local Persistent Store**: All metadata stored in your own PostgreSQL — independent of platform availability
- **Excel/CSV Export**: Customer-data-safe with masking options and delta reporting
- **Multi-Tenant Support**: Full domain and project-level filtering and management
- **Comprehensive Audit System**: Change tracking, deletion history, compliance reporting, resource timeline

<details>
<summary><strong>User Management Details</strong></summary>

- **Multi-Domain User Collection**: 100+ users across 28 OpenStack domains
- **Role Assignment Tracking**: Monitors role assignments across the infrastructure
- **Activity Monitoring**: User last-seen timestamps and account status
- **Role Inference System**: Intelligent role assignment when API access is limited
- **Domain-Scoped Authentication**: Complete user enumeration across tenants
- **LDAP Password Reset** *(v1.40)*: Superadmin can reset any LDAP user's password directly from the Users table — 🔑 button opens an inline form with SSHA-hashed password write, minimum-length validation, and full audit logging

</details>

### 🔄 Automated Snapshot Management
- **Built From Scratch**: No native scheduler exists in Platform9 or OpenStack — we built one
- **Metadata-Driven Policies**: Volume-level configuration via OpenStack metadata
- **Multi-Policy Support**: daily_5, monthly_1st, monthly_15th with independent retention per volume
- **Cross-Tenant Snapshots**: Dedicated service user architecture for correct tenant context
- **SLA Compliance Reporting**: Configurable thresholds with detailed tenant/domain aggregation
- **Policy Assignment Rules**: JSON-driven automatic policy assignment based on volume properties

<details>
<summary><strong>Snapshot System Components</strong></summary>

- **Automated Creation** (`snapshots/p9_auto_snapshots.py`): Policy-driven volume snapshots with retention management, dual-session architecture (admin for listing, service user for creating)
- **Service User Management** (`snapshots/snapshot_service_user.py`): Automatic admin role assignment per tenant project, Fernet-encrypted or plaintext password support
- **Policy Assignment** (`snapshots/p9_snapshot_policy_assign.py`): Opt-out rule engine, volume property matching, bulk metadata assignment
- **Compliance Reporting** (`snapshots/p9_snapshot_compliance_report.py`): Real-time SLA analysis, tenant/domain aggregation

</details>

### ⚡ Automated VM Restore *(No native equivalent exists in OpenStack)*
- **Full Restore Automation**: Flavor, network, IPs, user credentials, volume attachment — all handled
- **Side-by-Side Restore**: New VM with new name and IP alongside the original — non-destructive
- **Replace Restore**: Full recovery with original configuration — Superadmin-only with typed confirmation
- **IP Strategies**: NEW_IPS (DHCP), TRY_SAME_IPS (best-effort), SAME_IPS_OR_FAIL (strict)
- **3-Screen UI Wizard**: Guided restore flow with real-time progress tracking
- **Dry-Run Mode**: Validate the full restore plan before executing against OpenStack
- **Safety First**: Disabled by default, concurrent restore prevention, quota double-check, rollback on failure
- **Full Restore Audit**: Every operation logged — who, what mode, duration, outcome

### 👁️ Real-Time Monitoring
- **Host Metrics**: Live CPU, memory, storage from PF9 compute nodes via Prometheus node_exporter (port 9388)
- **VM Metrics**: Individual VM resource tracking via libvirt_exporter (port 9177)
- **Automated Collection**: Background collection every 30 minutes
- **Persistent Cache**: Metrics survive service restarts
- **Integrated Dashboard**: Real-time monitoring tab with auto-refresh

### 🔔 Smart Notifications
- **Event-Driven Alerts**: Snapshot failures, compliance violations, drift events, health score drops
- **System Alert Rules**: Automatic email when RVTools inventory sync fails consecutively (threshold configurable); recovery email on first success; state persisted in DB; configured via Admin UI → Notifications → Settings
- **Per-User Preferences**: Subscribe to specific event types with severity filtering (info/warning/critical)
- **Daily Digest**: Configurable daily summary aggregating all events from past 24 hours
- **SMTP Flexibility**: Authenticated and unauthenticated relay support, optional TLS
- **HTML Templates**: Professional Jinja2 email templates for each event type
- **Notification History**: Full delivery log with status tracking and retry information

### 💰 Metering & Chargeback
- **Per-VM Resource Tracking**: vCPU, RAM, disk allocation + actual usage, network I/O
- **Snapshot & Restore Metering**: Count, size, compliance, operation tracking
- **API Usage Metering**: Endpoint-level call counts, error rates, latency percentiles (avg/p95/p99)
- **Efficiency Scoring**: Per-VM classification (excellent/good/fair/poor/idle)
- **Multi-Category Pricing**: Compute, storage, snapshot, restore, volume, network — hourly + monthly rates
- **Chargeback Export**: Per-tenant cost breakdown with one-click CSV export
- **8 Sub-Tab UI**: Overview, Resources, Snapshots, Restores, API Usage, Efficiency, Pricing, Export

### 🏢 Customer Provisioning & Domain Management *(v1.16 → v1.34.2)*
- **5-Step Provisioning Wizard**: Domain → Project → User/Role → Quotas → Networks/Security Group
- **Multi-Network Support** *(v1.34.2)*: Add any combination of 3 network kinds per provisioning run:
  - 🔌 **Physical Managed** — provider/external VLAN network (`<domain>_tenant_extnet_vlan_<id>`)
  - 🔗 **Physical L2 (Beta)** — provider L2 network, no subnet (`<domain>_tenant_L2net_vlan_<id>`)
  - ☁️ **Virtual** — standard tenant network (`<domain>_tenant_virtnet[_N]`)
- **Dynamic Keystone Roles**: Fetches roles from PF9 Keystone, filters internal system roles
- **Tabbed Quota Editor**: Compute, Block Storage, Network tabs with "Set Unlimited" toggles
- **Network Auto-Discovery**: Physical networks from Neutron with VLAN/flat/VXLAN support
- **Customer Welcome Email**: HTML template listing all provisioned networks (kind, VLAN, subnet, gateway) per network card
- **Domain Management**: Full lifecycle — enable/disable, typed confirmation delete, resource inspection
- **Resource Deletion**: 8 DELETE endpoints for individual resources across all types
- **Central Activity Log**: Full audit trail for all provisioning and domain operations
- **DB Persistence**: `networks_config` + `networks_created` JSONB columns in `provisioning_jobs` store full input and output network details

### 📋 Reports & Resource Management *(v1.17 → v1.63)*
- **20 Report Types**: VM Report, Tenant Quota Usage, Domain Overview, Snapshot Compliance, Flavor Usage, Metering Summary, Resource Inventory, User/Role Audit, Idle Resources, Security Group Audit, Capacity Planning, Backup Status, Activity Log, Network Topology, Cost Allocation, Drift Summary, **Image Usage by Tenant** *(v1.40)*, **Flavor Usage by Tenant Detail** *(v1.40)*
- **BFV-aware reporting** *(v1.40)*: Image and Flavor by Tenant reports resolve instances booted from volume via Cinder `volume_image_metadata` — full VM counts including BFV workloads
- **CSV Export**: All reports support one-click CSV download
- **RVTools Exports Browser** *(v1.63)*: "📁 RVTools Exports" sub-tab inside Reports — file list (filename, size, date) with one-click authenticated download + run history table showing the last 100 `inventory_runs` entries (started, finished, duration, status badge)
- **Resource Provisioning Tool**: Full CRUD for Users, Flavors, Networks, Routers, Floating IPs, Volumes, Security Groups across tenants
- **Quota Management**: View and live-edit compute, network, and storage quotas per tenant
- **Safety Protections**: Last-user guard, in-use flavor check, attached-volume block, default SG protection
- **Three-Tier RBAC**: Viewer (read), Operator (read+write), Admin (read+write+delete)

### 🔍 Ops Assistant — Search & Similarity *(v1.20)*
- **Full-Text Search**: PostgreSQL tsvector + websearch across all 29 resource types, events, and audit logs
- **Trigram Similarity**: "Show Similar" per result — finds related resources, errors, or configurations via pg_trgm
- **Intent Detection**: Natural-language queries like *"quota for projectX"* or *"capacity"* auto-suggest the matching report endpoint
- **Smart Query Templates (v3)**: 26 question templates turn the search bar into an Ops Assistant — ask *"how many VMs are powered off?"*, *"quota for service"*, or *"show platform overview"* and get live answer cards inline
- **Scope Filters**: Domain and Tenant dropdowns filter smart query results to a specific project or domain — 20 of 26 query templates are scope-aware
- **Discoverability UI**: 🤖 button opens a categorised help panel with clickable example chips across 6 categories (Infrastructure, Projects & Quotas, Storage, Networking, Security & Access, Operations) — template chips auto-fill with the scoped tenant, instant chips run immediately. "New Question" button resets the search.
- **Quota & Usage Metering**: Background collector computes per-project resource consumption (VMs, vCPUs, RAM, volumes, storage, snapshots, floating IPs, networks, ports, security groups) from live inventory tables with flavor-based vCPU/RAM resolution
- **29 Indexed Document Types**: VMs, volumes, snapshots, hypervisors, networks, subnets, floating IPs, ports, security groups, domains, projects, users, flavors, images, routers, roles, role assignments, groups, snapshot policies, activity log, auth audit, drift events, snapshot runs/records, restore jobs, backups, notifications, provisioning, deletions
- **Incremental Indexing**: Background worker with per-doc-type watermarks — only re-indexes changed rows
- **Stale Cleanup**: Automatically removes search documents for deleted infrastructure resources
- **Paginated Results**: Relevance-ranked results with highlighted keyword snippets and metadata pill cards
- **Indexer Dashboard**: Real-time stats on document counts, last run time, and per-type health

### 📋 Policy-as-Code Runbooks *(v1.21 → v1.61)*
- **Runbook Catalogue**: Browse 25 built-in operational runbooks with schema-driven parameter forms:
  - **VM**: Stuck VM Remediation, VM Health Quick Fix, Snapshot Before Escalation, Password Reset + Console Access, **VM Rightsizing** *(v1.55)* — identifies over-provisioned VMs and suggests/executes flavor downsizing with pre-snapshot safety, **DR Drill** *(v1.56)* — clone DR-tagged VMs into isolated network, verify boot, auto-teardown, **Hypervisor Maintenance Evacuate** *(v1.57, Phase C2)* — drain a hypervisor before maintenance: live-migrate all VMs (graph-depth ordered), cold-migrate fallback, disable host after drain
  - **Security**: Security Group Audit, Security & Compliance Audit, User Last Login Report, Snapshot Quota Forecast, **Security Group Hardening** *(v1.57, Phase C)* — replaces 0.0.0.0/0 rules with graph-derived CIDRs, **Network Isolation Audit** *(v1.57)* — scans shared networks, cross-tenant routers, CIDR overlaps, and unexpected FIPs, **Image Lifecycle Audit** *(v1.57)* — scores images by age + EOL OS + FIP exposure
  - **Quota**: Quota Threshold Check, Upgrade Opportunity Detector, **Quota Adjustment** *(v1.53)* — sets Nova/Neutron/Cinder quota with billing gate + dry-run diff
  - **General**: Orphan Resource Cleanup, Diagnostics Bundle, Monthly Executive Snapshot, Cost Leakage Report, **Org Usage Report** *(v1.53)* — full usage + cost report with email-ready HTML body, **Capacity Forecast** *(v1.55)* — linear regression on cluster vCPU/RAM history, projects days to 80% capacity, **Cluster Capacity Planner** *(v1.61)* — HA-aware cluster capacity analysis: reserves N+1/N+2 host headroom, 70% safe-operating threshold, forecasts days to capacity, recommends minimum host spec for 6-month runway, per-flavor VM slot table
  - **Provisioning**: **Tenant Offboarding** *(v1.56)* — 10-step customer exit: FIP release → VM stop → port cleanup → Keystone disable → metadata tagging → CRM notification → final report email
- **Department Visibility** *(v1.52)*: Admins control which departments see each runbook via a live checkbox matrix in the UI; non-admin users receive only the runbooks their department is allowed to trigger
- **External Integrations** *(v1.52)*: Connect billing gates, CRM systems, or generic webhooks. `auth_credential` Fernet-encrypted at rest. Action runbooks call `_call_billing_gate()` for pre-authorization before applying changes — silently skips if no integration is configured
- **Result Export**: Every runbook result can be exported as CSV, JSON, or printed to PDF directly from the detail panel
- **ILS Pricing from Metering**: Cost-related runbooks pull real pricing from the `metering_pricing` table — per-flavor, per-resource, with automatic currency detection (ILS/USD)
- **Operator-Facing Trigger**: Tier 1 operators can browse and trigger runbooks with dry-run support — no admin access needed
- **Flexible Approval Workflows**: Configurable `trigger_role → approver_role` mapping per runbook with three modes: auto-approve, single approval, multi-approval
- **Admin Governance**: Execution History, Approvals queue, and Approval Policies managed via 3 dedicated sub-tabs in the Admin panel
- **Full Audit Trail**: Every execution records trigger user, approver, timestamps, parameters, results, items found/actioned
- **Pluggable Engine Architecture**: `@register_engine` decorator pattern — add new runbooks with zero framework changes

### 🕸️ Cloud Dependency Graph *(v1.47 → v1.51)*
- **BFS Graph Engine**: `GET /api/graph` — given any resource (VM, volume, network, tenant, snapshot, SG, FIP, subnet, port, host, image, domain), returns the full node+edge dependency graph up to 3 hops; 150-node cap with `truncated` flag
- **12 Node Types, 15 Edge Types**: All relationships derived from the existing DB schema with no schema changes required
- **Health Score Engine** *(v1.51)*: Every node shows a coloured 0–100 score circle; VM/volume/host each have tailored deduction rules for error states, missing snapshots, drift, and resource pressure; capacity pressure tinting on host nodes
- **Blast Radius Mode** *(v1.51)*: Click 💥 to highlight all resources impacted if the selected node fails; animated edges + node dimming; summary banner showing affected VMs, tenants, FIPs, and volumes
- **Delete Impact Mode** *(v1.51)*: Click 🗑 to preview cascade deletions, stranded resources, and OpenStack blockers before any destructive action
- **Orphan Detection** *(v1.51)*: Surfaces orphaned volumes (unattached), floating IPs (no port), security groups (unused), and dangling snapshots; visible in Tenant Health Panel
- **Tenant Health Panel** *(v1.51)*: Environment health score, critical/degraded VM counts, orphan count, expandable top-issues list shown above the canvas in Topology mode
- **VMware Migration Graph** *(v1.48)*: RVTools-side dependency graph with VM, disk, and portgroup/VLAN nodes; migration status rings (🟢 complete / 🟡 in progress / 🔴 failed); view from any Migration Planner tenant row or cohort expansion
- **ReactFlow UI** (`DependencyGraph.tsx`): Dagre hierarchical layout, 12 color-coded node types, depth pills (1/2/3), type filter checkboxes, **🔍 Explore from here** re-rooting with ← Back breadcrumb; **🔗 Open in tab**, **📸 Create Snapshot**, and **🚀 View in Migration Planner** quick actions on any node
- **Auto-Ticket Integration** *(v1.59)*: Graph node health score < 40 triggers `auto_incident` ticket; `POST /api/graph/request-delete` creates an `auto_change_request` before any destructive delete

### 🤖 Ops Copilot — AI Infrastructure Assistant *(v1.24)*
- **Three-Tier Architecture**: Built-in intent engine (zero setup) → Ollama (local LLM) → OpenAI/Anthropic (external LLM)
- **40+ Built-in Intents**: Inventory counts, VM power states, capacity metrics, error VMs, down hosts, networking (networks, subnets, routers, floating IPs), snapshot/drift/compliance summaries, user lists, role assignments, activity logs, runbook status, and full infrastructure overview — all powered by live SQL queries
- **Tenant / Project / Host Scoping**: Add "on tenant X", "for project X", or "on host Y" to any question for filtered results. Synonym expansion ensures natural phrasing always matches.
- **LLM Integration**: Free-form questions answered via Ollama (local, no data leaves your network) or OpenAI/Anthropic (with automatic sensitive data redaction)
- **Labeled FAB + Welcome Screen**: Prominent pill-shaped "🤖 Ask Copilot" button with pulse animation on first visit, welcome screen with examples, and a dedicated help view with 8 categorized question groups and usage tips
- **Admin Settings Panel**: Switch backends, configure URLs/keys/models, edit system prompts, test connectivity — all from the UI, no `.env` edits needed
- **Feedback & History**: Per-answer thumbs up/down, conversation history persisted per user with automatic trimming
- **Automatic Fallback**: If the LLM backend fails, seamlessly falls back to the built-in intent engine

### 🌐 Multi-Region & Multi-Cluster Support *(v1.73.0 → v1.79.0)*

**For MSPs managing multiple Platform9 customers or data centres, this is the operational core.**

A single pf9-mngt instance can connect to any number of Platform9 installations and OpenStack regions. Every view — inventory, metering, snapshots, reports, migration planner — automatically scopes to the selected region, or aggregates across all regions simultaneously.

**The MSP use case**: your company manages 4 customers, each on their own PF9 cluster. Without multi-cluster support you run 4 separate tools, correlate data manually, and switch contexts manually. With pf9-mngt you register all 4 control planes, and one console covers everything: per-customer inventory, per-customer chargeback, per-customer snapshot SLA, per-customer migration planning — with a region selector that switches context in one click.

#### Architecture
- **Two-level hierarchy** that mirrors OpenStack natively — one **control plane** per PF9 installation (one Keystone endpoint, shared identity), with one or more **regions** per control plane (each with its own Nova/Neutron/Cinder/Glance endpoints and independent resource inventory)
- **ClusterRegistry** replaces the legacy global `Pf9Client` singleton — the registry holds one authenticated client per region, manages sessions, and routes all API calls to the correct endpoint
- **Zero-migration rollout** — existing single-region deployments are automatically seeded on first startup; `PF9_AUTH_URL` + `PF9_REGION_NAME` become the `default` control plane and region; no operator action required

#### Management UI *(v1.76.0)*
- **Region Selector** — compact dropdown in the top nav bar, visible only when 2 or more regions are registered; groups options by control plane with live health-state colour dots (green / yellow / red / grey)
- **Cluster Management admin panel** — superadmin-only tab to add/delete/test control planes, discover and register regions with one click, enable/disable regions, trigger manual syncs, and view sync logs; no env-var changes or restarts required to add a new cluster

#### Per-Region Everything
- All infrastructure resources — VMs, volumes, networks, snapshots, provisioning jobs, search index, metering rows — carry a `region_id` FK; full per-region inventory, reporting, and audit trail
- All 7 API modules accept an optional `?region_id=` parameter to scope any query to a specific region, or aggregate across all regions when omitted
- **RBAC enforcement**: region-scoped users are automatically constrained to their assigned region (HTTP 403 on mismatch); global users may query any region
- All background workers (metering, snapshot, scheduler, search) run independent per-region loops — a slow or failed region does not block collection for healthy regions
- Redis cache keys are namespaced by `region_id` — no cross-region cache collisions

#### Cross-Region Migration Planning *(v1.77.0)*
- Migration projects can now be linked to registered regions via `target_region_id` — `pcd-gap-analysis` uses the ClusterRegistry client for live feasibility checks against that registered region, with full backward compatibility for ad-hoc credentials
- `GET /admin/control-planes/cluster-tasks` — superadmin endpoint exposing the `cluster_tasks` cross-region task bus; snapshot replication / DR failover deferred pending second-region testing infrastructure

#### Operational Resilience
- **Per-region health tracking**: `health_status` per region (`healthy` / `degraded` / `unreachable` / `auth_failed`), sync metrics, and last-sync timestamp
- **Per-region timeout**: each region call enforces a hard `asyncio.wait_for` deadline (`REGION_REQUEST_TIMEOUT_SEC`, default 30 s) — an unreachable region cannot stall all others
- **SSRF protection**: each control plane has `allow_private_network` (default `false`) — blocks RFC-1918 and loopback outbound connections; configurable per-CP by superadmin for on-premises clusters

> 📖 See the dedicated **[Multi-Region & Multi-Cluster Guide](docs/MULTICLUSTER_GUIDE.md)** for a step-by-step operator walkthrough.

### �🎫 Support Ticket System *(v1.58 → v1.60)*
- **Full Ticket Lifecycle**: Ticket refs (TKT-YYYY-NNNNN); 5 types (incident, service_request, change_request, auto_incident, auto_change_request); full status/priority/type model; approval gate; SLA deadlines; OpenStack resource linkage
- **35+ API Endpoints** at `/api/tickets`: create, list, get, update, assign, escalate, approve/reject, resolve/reopen/close, comment thread, SLA policies, email templates, analytics, bulk actions
- **SLA Daemon**: Background asyncio task (15-min interval) — breach detection, Slack/Teams notification, auto-escalate on breach, activity comment logged
- **Auto-Ticket Triggers** *(v1.59)*: Critical/warning drift events → `auto_incident`; health score < 40 → `auto_incident`; graph delete intent → `auto_change_request` with `auto_blocked` gate; runbook failure → `auto_incident` linked to execution; migration wave complete → `service_request`
- **Ticket Analytics** *(v1.60)*: Resolution time by dept, SLA breach rate, top openers, daily volume trend; **LandingDashboard KPI tile** (Open / SLA Breached / Resolved Today / Opened Today)
- **Bulk Actions** *(v1.60)*: `close_stale`, `reassign`, `export_csv` via checkbox multi-select toolbar
- **Integration**: Trigger runbooks from a ticket and attach results; `email-customer` action via named HTML templates; inline ticket creation from Metering and Runbooks rows; team-member assignment at creation
- **5 DB Tables**: `support_tickets`, `ticket_comments`, `ticket_sla_policies`, `ticket_email_templates`, `ticket_sequence`; 17 seeded SLA policies, 6 HTML email templates
- **Navigation**: New "Operations & Support" group (🎫) with Tickets and My Queue items

### 📊 Operational Intelligence *(v1.86.0 → v1.92.0)*

**Continuous, background-running insight engine for MSP and enterprise infrastructure operators.**

The `intelligence_worker` runs 6 detection engines every 5 minutes and writes structured insights to `operational_insights`. Insights are categorised by department (operations, finance, general), severity (info/medium/high/critical), and type. Expired conditions auto-resolve.

- **Waste engine** *(v1.86.0)*: Detects idle VMs (powered off ≥7d, powered off ≥14d) and orphaned resources (unattached volumes, dangling FIPs, unused security groups).
- **Risk engine** *(v1.86.0)*: Detects critical health decline (score drops ≥20 pts in 7d) and snapshot gaps (VMs without snapshot coverage ≥7d). Auto-creates `auto_incident` tickets for critical findings.
- **SLA engine** *(v1.86.0)*: Detects imminent SLA breaches (≤48 h to deadline for open tickets). Monthly PDF report: `POST /api/sla/generate-report/{tenant_id}` — cover page, KPI scorecard, history table, attestation footer.
- **Capacity engine** *(v1.89.0)*: Per-hypervisor compute saturation forecast (`capacity_compute`), per-project quota saturation (`capacity_quota_*`), and storage quota pressure. All include `confidence` + `r_squared` metadata.
- **Cross-region + Anomaly engine** *(v1.89.0)*: Utilization imbalance, risk concentration, VM-count spikes, snapshot spikes, API error spikes.
- **Revenue Leakage engine** *(v1.90.0)*: `leakage_overconsumption` — tenant resources exceed contracted entitlement by ≥10% (medium at 10–25%, high at >25%). `leakage_ghost` — tenant has active resources but no contract row. Requires `msp_contract_entitlements` rows to be populated.

**QBR PDF Generator** *(v1.90.0)*: `POST /api/intelligence/qbr/generate/{tenant_id}` — configurable sections (cover, executive_summary, interventions, health_trend, open_items, methodology). Sections build from resolved insights × labor rates for defensible ROI reporting.

**PSA Outbound Webhook** *(v1.90.0)*: `GET/POST/PUT/DELETE /api/psa/configs`. Per-config filtering: min severity, insight types allow-list, region IDs allow-list. Auth header Fernet-encrypted at rest. Webhooks fire from the intelligence worker on new high/critical insights — no cross-service HTTP dependency.

**Intelligence Settings Panel** (admin-only, `⚙️ Settings` tab in InsightsTab): Labor rates editor (8 types, cost-per-hour), PSA Webhook CRUD with test-fire, Contract Entitlements CSV importer.

**Insights Feed UI** *(v1.86.0 → v1.91.0)*: Department workspace selector (operations, risk, capacity, general), severity badges, per-insight acknowledge/snooze/resolve, bulk actions, recommendation panel, per-insight recommendations with dismiss. Type filter optgroup: Waste, Risk, SLA, Capacity, Anomaly, Cross-Region, Revenue Leakage. Sort by: severity, detected, last seen, type, entity, tenant, status (7 options). Copilot intents: critical_insights, capacity_warnings, waste_insights, unacknowledged_insights_count, risk_summary.

**Insights History tab** *(v1.91.0)*: “🕐 History” sub-tab in the Insights Dashboard showing resolved insights with detected/resolved timestamps, paginated at 50 per page.

**Operations workspace summary bar** *(v1.91.0)*: When the Operations workspace is selected, a summary bar above the feed shows total open, risk, waste, and leakage insight counts in colour-coded badges.

**Client Health endpoint** *(v1.91.0, fixed v1.93.12)*: `GET /api/intelligence/client-health/{tenant_id}` — Efficiency score (avg `metering_efficiency.overall_score` last 7 days + verbal classification), Stability score (100 minus severity-weighted open insights: critical −20, high −10, medium −5), Capacity Runway (days until soonest resource hits 90% quota, from `metering_quotas` linear regression). RBAC: `client_health:read` (viewer, operator, admin, superadmin). *v1.93.12: endpoint now resolves the project UUID to its human-readable name before querying `metering_efficiency`, fixing Efficiency always returning 0 when called with a project UUID.*

**Portfolio summary endpoint** *(v1.92.0)*: `GET /api/sla/portfolio/summary` — Per-tenant portfolio view for account managers. Returns a row per managed client with `sla_status` (healthy/at_risk/breached/not_configured), `contracted_vcpu`, `used_vcpu`, `contract_usage_pct`, `open_critical_count`, `open_total_count`, `leakage_insight_count`. RBAC: `sla:read`.

**Executive summary endpoint** *(v1.92.0)*: `GET /api/sla/portfolio/executive-summary` — Fleet-level aggregation: `total_clients`, `sla_healthy/at_risk/breached/not_configured`, `sla_health_pct`, `revenue_leakage_monthly` (null when no `unit_price` set), `leakage_client_count`, `open_critical_insights`, `avg_mttr_hours`, `avg_mttr_commitment_hours`. RBAC: `sla:read`.

**Account Manager Dashboard** *(v1.92.0, `account_manager_dashboard` tab)*: React component with 6-card KPI strip, filter/search bar, and per-tenant table (SLA badge, vCPU usage bar, critical badge, leakage badge, breach fields). New `account_manager` RBAC role; `Account Management` department with `default_nav_item_key = account_manager_dashboard` for persona auto-routing on login.

**Executive Dashboard** *(v1.92.0, `executive_dashboard` tab)*: Fleet-level stacked SLA health bar, 6 KPI cards (Fleet Health %, Breached, At Risk, Open Critical, Revenue Leakage/Month, Avg MTTR), and narrative sections for leakage and MTTR compliance. New `executive` RBAC role; `Executive Leadership` department with `default_nav_item_key = executive_dashboard`.

### 🏢 Tenant Self-Service Portal *(v1.84.0+, latest v1.92.0)*

**For MSPs and operators who want to give customers limited, secure access to their own infrastructure — with self-service VM provisioning, security group management, and read-only observer access — without exposing the admin panel.**

A separate FastAPI service on port 8010 (`tenant_portal/`) provides a JWT-isolated, MFA-protected API and accompanying React SPA (`tenant-ui/`) per customer. Tenants can monitor their VMs, browse snapshots, initiate restores, manage security groups, view a dependency graph, provision new VMs, and inspect their health scores — all scoped to their own projects only.

- **Observer role** *(v1.91.0)*: `portal_role` column on `tenant_portal_access` (`manager` | `observer`). Observer JWT tokens are blocked at the FastAPI dependency layer (`require_manager_role()`) from all 8 write routes. Role persists through TOTP/email-OTP MFA flows, is embedded as a JWT claim, and is toggleable per-user from the admin UI without disrupting the session.
- **Observer invite flow** *(v1.91.0)*: `POST /api/intelligence/invite-observer` generates a one-time `portal_invite_tokens` row and sends a branded HTML email with a magic-link. Tokens expire and are one-time-use enforced by `used_at`.
- **Health Overview screen** *(v1.91.0, fixed v1.93.12)*: New default landing screen in `tenant-ui` with three SVG circular progress dials (Efficiency, Stability, Capacity Runway) sourced from `GET /tenant/client-health` — a proxy to the admin API `client-health` endpoint. *v1.93.12: Capacity Runway dial now shows a neutral grey ring when no quota ceiling is configured (was showing a misleading red "0"); Efficiency score bug fixed (was always 0 due to UUID→name mismatch in the upstream query).*

- **Security isolation**: `tenant_portal_role` PostgreSQL role with Row-Level Security on 5 inventory tables. `role=tenant` JWT namespace (admin tokens explicitly rejected). IP binding + Redis session binding. TOTP + email OTP MFA with 8 bcrypt-hashed backup codes.
- **Data endpoints (read-only)**: VM inventory, volume list, snapshot list/detail/history, per-VM compliance %, dashboard summary, event feed, Prometheus metrics proxy (scoped to tenant VMs), runbooks catalogue — 14 routes, all with double `project_id + region_id` scoping and RLS.
- **Restore center**: 6 endpoints (list restore points, dry-run plan, execute, list jobs, progress, cancel). Side-by-side restore always creates a new VM — non-destructive. Ops Slack/Teams alert on execute; tenant email on completion/failure.
- **Network & SG Management** *(v1.85.0)*: `GET /tenant/networks` (subnets, CIDRs, shared/external); `GET /tenant/security-groups/{id}` (rules); `POST/DELETE /tenant/security-groups/{id}/rules` (add/delete rules via Neutron + local DB sync). Internal endpoints: `POST /internal/sg-rule`, `DELETE /internal/sg-rule/{id}`.
- **Dependency Graph** *(v1.85.0, expanded v1.85.3)*: `GET /tenant/resource-graph` returns VM, network, subnet, SG, and volume nodes with 4 edge types (`vm_network`, `vm_sg`, `network_subnet`, `vm_volume`). Rendered as a 5-column SVG layout with colored nodes and legend.
- **VM Provisioning** *(v1.85.0, enhanced v1.85.3)*: `POST /tenant/vms` → `POST /internal/tenant-provision-vm` → `create_boot_volume` + `create_server_bfv`. RFC-1123 name validation, fixed IP picker (subnet CIDR hint), cloud-init user/password fields, boot volume size display. New *New VM* screen (🚀) in the tenant portal nav.
- **K8s crash hotfix** *(v1.85.12)*: `pf9-tenant-ui` nginx config hardcoded Docker Compose service name `tenant_portal` → K8s DNS fails → CrashLoopBackOff. Fixed with envsubst template; Helm sets `TENANT_PORTAL_UPSTREAM=pf9-tenant-portal:8010`. `pf9-monitoring` missing `httpx` in requirements → `ModuleNotFoundError` at startup → CrashLoopBackOff. Added `httpx==0.27.2`.
- **Production fix + branding + error messages + Restore Center** *(v1.85.11)*: `tenant-ui` nginx now proxies `/tenant/*` to `tenant_portal` (was missing — entire portal broken in prod). Branding logo served as base64 data URL for legacy file-path `logo_url` values. `apiFetch` 422 detail-array unwrapped (eliminates `[object Object]` error messages in admin UI). Restore Center: `MANUAL_IP` network/IP selection, post-restore result panel, email summary, expandable history.
- **K8s stability (v1.85.7)**: `apiFetch` no-retry-on-HTTP; quota CP ID slug support; snapshot calendar today-cell highlight; `apiExecuteRunbook` normalised + `RiskBadge`/`statusBadge` null-guarded; monitoring `cache_available` flag in API response + improved empty-state.
- **Per-tenant branding** *(v1.85.6)*: `tenant_portal_branding` table gains `project_id` column (empty = CP-level default); admin scope dropdown to select per-tenant override; `useBranding` re-fetches after login.
- **Runbook Execution** *(v1.85.3)*: `POST /tenant/runbooks/{name}/execute`, `GET /tenant/runbook-executions`; internal `POST /internal/tenant-runbook-execute`, `GET /internal/tenant-runbook-executions`. Execute dialog with dynamic parameter form, dry-run toggle, risk warning banner, execution history tab.
- **VM List & Inventory** *(v1.85.3)*: `disk_gb` via `flavors` JOIN; IP addresses from `raw_json`; both in Infrastructure table and inventory CSV export.
- **Activity Log** *(v1.85.3)*: *User* column — `username` + truncated `keystone_user_id` from `GET /tenant/events`; system events show "system".
- **Dashboard** *(v1.85.3)*: Skipped snapshot events display amber "Skipped" badge instead of red "Failed".
- **Audit logging**: every tenant API call writes an immutable `tenant_action_log` entry atomically with the data query.
- **Branding** *(v1.84.9)*: `GET /tenant/branding` unauthenticated endpoint returns per-CP logo URL, accent colour, portal title, and favicon. 60 s Redis cache; fail-safe defaults when unconfigured.
- **Web SPA** (`tenant-ui/`): React + TypeScript + nginx — 10 screens: Health Overview (default, v1.91.0), Dashboard, Infrastructure (VMs · Volumes · Networks · Security Groups · Dependency Graph), Snapshot Coverage, Monitoring, Restore Center, Runbooks, Reports, New VM (🚀 Provision), Activity Log. Per-customer branding applied from server. Session token silently re-validates on page reload.
- **Admin API** (`api/tenant_portal_routes.py`): 9 admin endpoints — user listing, access management (grant/revoke projects), session management (list/revoke), audit log review, branding upsert *(v1.84.9)*, MFA reset *(v1.84.9)*. Requires `admin` or `superadmin`.
- **Admin UI** *(v1.84.9)*: `TenantPortalTab.tsx` — 4 sub-tabs: Access Management, Branding (logo + accent colour editor), Active Sessions, Audit Log.
- **Kubernetes**: dedicated `nginx-ingress-tenant` Helm release on separate MetalLB IP *(v1.84.8)*; `NetworkPolicy` blocks tenant portal from reaching admin API, LDAP, and SMTP.
- **Security test suite** *(v1.84.9, P8)*: 27 tests (S01–S27) covering unauthenticated access control, token segregation, CSRF resistance, rate limiting, input validation, session invalidation, MFA bypass resistance, and cross-tenant data isolation.

### 📈 30+ Tab Management Dashboard
A single engineering console covering every operational surface:

> Servers · Volumes · Snapshots · Networks · Security Groups · Subnets · Ports · Floating IPs · Domains · Projects · Flavors · Images · Hypervisors · Users · Roles · Snapshot Policies · History · Audit · Monitoring · Restore · Restore Audit · Notifications · Metering · Customer Provisioning · Domain Management · Activity Log · Reports · Resource Management · **Ops Search** · **Runbooks** · **Ops Copilot** · **Tickets** · **Dependency Graph** · **Operational Intelligence** · **SLA Compliance** · **Business Review (QBR)** · **My Portfolio (Account Manager)** · **Portfolio Health (Executive)**

<details>
<summary><strong>Landing Dashboard Widgets</strong></summary>

- **Health Summary Card**: System-wide metrics (VMs, volumes, networks, resource utilization)
- **Snapshot SLA Compliance**: Tenant-level compliance tracking with warning/critical alerting
- **Top Host Utilization**: Real-time CPU/memory usage across compute nodes
- **Recent Activity Widget**: Last 24 hours of infrastructure changes
- **Coverage Risk Analysis**: Volumes without snapshot protection
- **Capacity Pressure Indicators**: Storage and compute capacity warnings
- **VM Hotspots**: Top resource consumers (CPU/memory/storage)
- **Tenant Risk Scores**: Multi-factor risk assessments per tenant
- **Compliance Drift Tracking**: Policy adherence trending
- **Capacity Trends**: 7-day resource utilization forecasting
- **Trendlines**: Infrastructure growth patterns and velocity metrics

</details>

<details>
<summary><strong>History Tab Features</strong></summary>

- Filter by resource type (server, volume, snapshot, deletion, etc.), project, domain, and free-text search
- Sortable column headers with ascending/descending indicators
- Deletion record viewing — shows deletion timeline, original resource type, reason, and last-known state
- Most frequently changed resources section with direct history navigation
- Configurable timeframe (1 hour to 1 week)

</details>

- **Dark/Light Mode**: Full theme support with persistent preferences
- **Role-Based UI**: Tabs and actions shown based on user permission level
- **Write-Capable Indicators**: 🔧 icon marks tabs that can create, modify, or delete resources
- **Auto-Refresh**: 30-second refresh on dashboard, efficient pagination across all endpoints

### API Observability
- **Public Metrics**: `GET /metrics`
- **Authenticated Metrics (UI)**: `GET /api/metrics` — Admin/Superadmin only
- **Authenticated Logs (UI)**: `GET /api/logs` — with `limit`, `level`, `source`, `log_file` params
- **Swagger Docs**: `GET /docs` — interactive API documentation

---

