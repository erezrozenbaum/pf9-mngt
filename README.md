# pf9-mngt

> Provisioning infrastructure is solved.  
> Operating it at scale is not.

**pf9-mngt** is a self-hosted operational control plane for Platform9 / OpenStack. It adds the persistent inventory, automated recovery workflows, and governance layer that Platform9 itself does not provide — built for the teams responsible for what happens *after* Day-0.

<p align="center">
  <strong>Operational Control Plane for Platform9 / OpenStack</strong><br>
  Visibility &nbsp;·&nbsp; Recovery &nbsp;·&nbsp; Operations &nbsp;·&nbsp; Intelligence
</p>

<p align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.89.0-blue.svg)](CHANGELOG.md)
[![CI](https://github.com/erezrozenbaum/pf9-mngt/actions/workflows/ci.yml/badge.svg)](https://github.com/erezrozenbaum/pf9-mngt/actions/workflows/ci.yml)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-Helm%20%7C%20ArgoCD-326CE5?logo=kubernetes&logoColor=white)](docs/KUBERNETES_GUIDE.md)
[![Demo Mode](https://img.shields.io/badge/Try%20Demo%20Mode-no%20Platform9%20needed-brightgreen.svg)](#-try-it-now--demo-mode-no-platform9-required)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-orange.svg)](https://www.buymeacoffee.com/erezrozenbaum)

</p>

> ⭐ If pf9-mngt saves your team time, [**star the repo**](https://github.com/erezrozenbaum/pf9-mngt) — it helps others find it.

---

## 🔄 What This Actually Replaces

| Without pf9-mngt | With pf9-mngt |
|-----------------|--------------|
| Scripts that dump inventory to CSV, manually maintained | Persistent PostgreSQL inventory, 29 resource types, always current |
| VM restore = manual reconstruction at 3am under SLA pressure | Fully automated restore — flavor, network, IPs, volumes, credentials |
| No snapshot scheduler → custom cron per tenant, no SLA tracking | Policy-driven snapshot automation, cross-tenant, quota-aware, SLA-compliant |
| Migration planning in spreadsheets → guesswork | End-to-end planner: RVTools → risk scoring → wave planning → PCD provisioning |
| Separate ticketing tool + separate runbook wiki + separate billing exports | Built-in: tickets, 25 runbooks, metering, chargeback — one system |
| Tenants call you for every status check → your team is the bottleneck | Tenant self-service portal: customers view their own VMs, snapshots, and restores — scoped, isolated, MFA-protected |

One system. No duct tape.

---

## 🧭 What It Gives You

pf9-mngt adds a persistent operational layer on top of Platform9 / OpenStack, combining inventory, automation, recovery workflows, and governance into a single self-hosted system:

- **Full infrastructure visibility** — all metadata in your own PostgreSQL, independent of platform uptime, 29 resource types, cross-tenant
- **Automated snapshot & restore workflows** — no native equivalent exists in Platform9 or OpenStack; fully automated, SLA-tracked, audited
- **VMware → OpenStack migration planning** — end-to-end from RVTools ingestion to PCD auto-provisioning
- **Governance, audit, and Day-2 tooling** — runbooks, tickets, metering, chargeback, tenant self-service

Works alongside Platform9 via its APIs. Not a replacement — an operational layer on top.

---

## 🚨 The Day-2 Operations Reality

Provisioning is not the hard part anymore.

Running infrastructure at scale is.

What actually breaks in real Platform9 / OpenStack environments:

- **Snapshot SLAs** across tenants — no native scheduler exists
- **VM restore under pressure** — no native workflow; everything is manual reconstruction
- **Metadata ownership** — resource names, relationships, and topology live on the platform, not with you
- **Cross-tenant visibility** at scale — the native UI is per-tenant, not operational-aggregate
- **Multi-region complexity** — managing multiple clusters with no unified console
- **Coordination gaps** — between support, engineering, and management teams
- **Customer self-service** — tenants need to see their own infrastructure status without you being a human API; the native Platform9 UI is admin-only

These are **Day-2 operations problems**. pf9-mngt solves them.

---

## 💡 What pf9-mngt Is

A self-hosted operational platform that **extends** Platform9 / OpenStack — not replaces it.

- A **persistent inventory engine** — all Platform9 / OpenStack metadata in your own PostgreSQL, always available, independent of platform uptime (the RVTools equivalent for OpenStack)
- A **snapshot automation engine** — no native scheduler exists in Platform9 or OpenStack; this one is quota-aware, cross-tenant, policy-driven, with SLA compliance reporting
- A **VM restore system** — full automation of flavor, network, IPs, credentials, and volumes; two modes (side-by-side and replace); no native equivalent exists in OpenStack
- A **migration planning workbench** — from RVTools ingestion through cohort design, wave planning, and PCD auto-provisioning
- A **unified engineering console** — 30+ management tabs, RBAC, metering, chargeback, runbooks, tickets, and AI Ops Copilot
- A **tenant self-service portal** — a completely isolated, MFA-protected web interface that gives customers read + restore access to their own infrastructure without touching your admin panel; access is opt-in per Keystone user, controlled by you

✔ Works alongside Platform9 via its APIs &nbsp;·&nbsp; ❌ Not a UI replacement &nbsp;·&nbsp; ❌ Not an official Platform9 product

---

## 🔑 Four Pillars

Everything in pf9-mngt is built around four operational concerns:

| Pillar | What it covers |
|--------|---------------|
| 🔭 **Visibility** | Cross-tenant, multi-region inventory with drift detection, dependency graph, and historical tracking — metadata owned by you, not the platform |
| ♻️ **Recovery** | Snapshot automation and full VM restore orchestration — two modes, dry-run validation, SLA compliance, no native equivalent in OpenStack |
| 🎫 **Operations** | Ticketing, 25 built-in runbooks, metering, chargeback, standardized governance workflows, and tenant self-service portal |
| 🤖 **Intelligence** | AI Ops Copilot (plain-language queries against live infrastructure), capacity and risk scoring, VMware migration planning end-to-end |

> Everything else in the system — LDAP, multi-region, Kubernetes, export reports — supports one of these four pillars.

---

## 🧠 Why This Matters

| Challenge | Native Platform9 | pf9-mngt |
|-----------|-----------------|----------|
| Cross-tenant visibility | Per-tenant only | Centralized persistent inventory |
| Snapshot SLA enforcement | None built-in | Policy-driven, multi-tenant, audited |
| VM restore workflow | Manual reconstruct | Full automation, two modes, dry-run |
| Metadata ownership | Lives on the platform | Your PostgreSQL, always available |
| Multi-region ops | Operationally complex | Unified console, one-click context switch |
| Day-2 workflows | External tools | Built-in tickets, runbooks, metering |
| VMware migration | No native tooling | End-to-end planner: RVTools → PCD |
| Tenant visibility | You are the human API | Self-service portal: MFA-protected, RLS-isolated, scoped to their projects |

---

## 🔥 What Makes It Different

Most platforms solve provisioning.

pf9-mngt solves **what happens after deployment** — the snapshot SLAs that must hold, the 3am restore that must succeed, the compliance report due tomorrow, the capacity forecast before the cluster fills up, the VMware migration that has to go right.

Built from real-world operations. 410+ commits, 122 releases, 18 containerized services.

Not theory — from what actually breaks in production.

---

## ⚡ Try It Now — Demo Mode (No Platform9 Required)

Explore the full dashboard without a Platform9 environment:

```powershell
git clone https://github.com/erezrozenbaum/pf9-mngt.git
cd pf9-mngt
.\deployment.ps1   # select option 2 — Demo
```

Populates the database with 3 tenants, 35 VMs, 50+ volumes, snapshots, drift events, compliance reports, and a metrics cache. Every dashboard, report, and workflow is fully functional — no live cluster needed.

> **UI:** http://localhost:5173 &nbsp;·&nbsp; **API Docs:** http://localhost:8000/docs

---


## ⚡ What You Get in 30 Seconds

After running Demo Mode you'll find:

- **3 tenants** preloaded with realistic VM topology and metadata
- **35 VMs** with volumes, snapshot policies, and compliance reports
- **Migration plan example** — risk-scored VMs, cohort design, wave planning
- **Ticketing + runbook system** — full lifecycle, SLA tracking, 25 built-in procedures
- **Dashboard KPIs, drift events, and audit trail** — every workflow wired up

> No Platform9 cluster required. Full product experience in under 5 minutes.

---

## 🏗️ Architecture

**18-container microservices platform:**

| Service | Stack | Port | Purpose |
|---------|-------|------|---------|
| **nginx (TLS proxy)** | nginx:1.27-alpine | 80/443 | HTTPS termination, HTTP→HTTPS redirect, reverse proxy to API and UI |
| **Frontend UI** | React 19.2+ / TypeScript / Vite | 5173 | 30+ management tabs + admin panel |
| **Backend API** | FastAPI / Gunicorn / Python | 8000 | 170+ REST endpoints, RBAC middleware, 4 workers + --max-requests 1000 |
| **Redis** | redis:7-alpine | internal | OpenStack inventory/quota cache (60–300 s TTL, allkeys-lru, 128 MiB cap) |
| **LDAP Server** | OpenLDAP | internal | Enterprise authentication directory (not exposed to host) |
| **LDAP Admin** | phpLDAPadmin | 8081 *(dev profile)* | Web-based LDAP management (`--profile dev`) |
| **Monitoring Service** | FastAPI / Python | 8001 | Real-time metrics via Prometheus |
| **Database** | PostgreSQL 16 | internal | 95+ tables, audit, metering, migration planner, tenant portal RLS (not exposed to host) |
| **Database Admin** | pgAdmin4 | 8080 *(dev profile)* | Web-based PostgreSQL management (`--profile dev`) |
| **Snapshot Worker** | Python | — | Automated snapshot management |
| **Notification Worker** | Python / SMTP | — | Email alerts for drift, snapshots, compliance |
| **Backup Worker** | Python / PostgreSQL | — | Scheduled DB + LDAP backups to NFS, restore *(backup profile)* |
| **Scheduler Worker** | Python | — | Host metrics collection + RVTools inventory (runs inside Docker) |
| **Metering Worker** | Python / PostgreSQL | — | Resource metering every 15 minutes |
| **Search Worker** | Python / PostgreSQL | — | Incremental full-text indexing for Ops Assistant |
| **LDAP Sync Worker** | Python / PostgreSQL / OpenLDAP | — | Bi-directional DB ↔ LDAP sync, polls every 30 s |
| **Tenant Portal API** | FastAPI / Gunicorn / Python | 8010 | Tenant self-service portal — JWT + RLS, MFA, per-user access allowlist |
| **Tenant Portal UI** | React 19.2+ / TypeScript / nginx | 8083 *(dev: 8082)* | Tenant self-service web interface — 9 screens, MFA login, per-customer branding, VM provisioning, SG rule editing, dependency graph |

![Architecture](docs/images/Architecture.png)

> `pf9_scheduler_worker` (Docker container) runs `host_metrics_collector.py` (every 60 s) and `pf9_rvtools.py` (configurable interval or daily schedule) for infrastructure discovery and metrics collection. No Windows Task Scheduler dependency.

---

## 📊 Feature Status

| Feature | Status |
|---------|--------|
| Inventory Engine (RVTools-style, 29 resource types) | ✅ Production |
| Snapshot Automation | ✅ Production |
| VM Restore (side-by-side + replace modes) | ✅ Production |
| Reports (20 types + CSV export) | ✅ Production |
| Customer Provisioning & Domain Management | ✅ Production |
| Metering & Chargeback | ✅ Production |
| Notifications (SMTP + Slack + Teams) | ✅ Production |
| Drift Detection | ✅ Production |
| Ops Assistant — Full-Text Search & Smart Queries | ✅ Production |
| Runbooks (25 built-in, dept visibility, approval workflows, **tenant execution**) | ✅ Production |
| External Integrations Framework (billing gate, CRM, webhooks) | ✅ Production |
| Dependency Graph: Health Scores, Blast Radius, Delete Impact | ✅ Production |
| Backup & Restore (DB) with Integrity Validation | ✅ Production |
| Inventory Versioning & Diff | ✅ Production |
| AI Ops Copilot | ✅ Production |
| Migration Planner (end-to-end) | ✅ Production |
| Support Ticket System (SLA, auto-tickets, approvals) | ✅ Production |
| Container Restart Alerting | ✅ Production |
| Multi-Region & Multi-Cluster Support | ✅ Production |
| External LDAP / AD Identity Federation | ✅ Production |
| Kubernetes Deployment (Helm + ArgoCD + Sealed Secrets) | ✅ Production |
| Tenant Self-Service Portal | ✅ Production |
| Tenant VM Provisioning (self-service) | ✅ Production |
| Tenant Network & Security Group Management | ✅ Production |
| SLA Compliance Tracking | ✅ Production |
| Operational Intelligence Feed | ✅ Production |

---


## 🧭 Why This Was Built

Built during a serious Platform9 evaluation — stress-testing real operational workflows revealed four gaps no native tooling covered: **metadata ownership** (no RVTools-equivalent for OpenStack), **VM restore** (no native workflow exists), **snapshot automation** (no native scheduler), and **VMware migration planning** (no native RVTools → PCD workflow).

Rather than pause the evaluation, we solved them. The result is pf9-mngt — 410+ commits, 122 releases, built using AI as a genuine engineering partner alongside regular responsibilities.

> Full engineering story and gap analysis: [docs/ENGINEERING_STORY.md](docs/ENGINEERING_STORY.md)

---

## 📸 Screenshots

### Landing Dashboard
![Landing Dashboard](docs/images/dashboard-overview.png)

### Snapshot Compliance Report
![Snapshot Compliance Report](docs/images/snapshot-compliance-report.png)

### VM Inventory
![VM Inventory](docs/images/VMs-inventory.png)

### History & Monitoring
![History & Monitoring](docs/images/History-monitoring.png)

### API Performance
![API Performance](docs/images/API-Performance.png)

### Snapshot Restore Process
![Snapshot Restore Process](docs/images/snapshot-restore-process.png)

### Snapshot Restore Audit
![Snapshot Restore Audit](docs/images/Snapshot-restore-audit.png)

---

## 🎬 Video Walkthrough

A 15-minute explainer video walking through the UI and key features:

[![Watch on YouTube](https://img.shields.io/badge/YouTube-Watch%20Video-red?logo=youtube)](https://www.youtube.com/watch?v=68-LQ9ugU_E)

▶️ [**PF9 Management System — Full UI Walkthrough (15 min)**](https://www.youtube.com/watch?v=68-LQ9ugU_E)

---

## ⚙️ Core Capabilities

### 🔍 Inventory & Drift Detection
Persistent inventory outside Platform9 — 29 resource types, historical tracking, drift detection across tenants, domain/project mapping, CSV / Excel export.

### 📸 Snapshot Automation & Compliance
Policy-based snapshots (daily / monthly / custom), cross-tenant execution, quota-aware batching, retention enforcement, SLA compliance tracking, full audit visibility.

### ♻️ Restore Workflows
Side-by-side and replace modes, dry-run validation, full flavor / network / IP / credentials / volume automation, concurrent-restore prevention, complete audit logging.

### 🗺️ Migration Planner
RVTools ingestion → VM risk scoring → tenant scoping → network + flavor mapping → cohort design with ease scoring → wave planning with approval gates → PCD auto-provisioning → migration summary with throughput modeling.

### 🌍 Multi-Region / Multi-Cluster
Register multiple Platform9 control planes and regions. All inventory, reporting, and workers are region-aware. Unified console with one-click context switch. No restart required to add a new cluster.

### 🎫 Ticketing System
Full incident / change / request lifecycle, SLA tracking, auto-ticketing from health events (health score < 40, drift, graph deletes, runbook failures), department workflows, approval gates.

### 📋 Runbooks
25 built-in operational procedures covering VM recovery, security audits, quota management, capacity forecasting, and tenant offboarding. Parameterized, dry-run support, approval flows, export to CSV / JSON / PDF — integrated with the ticket system.

### 📊 Metering & Chargeback
Per-VM resource tracking, snapshot / restore metering, API usage metrics, efficiency scoring (excellent / good / fair / poor / idle), multi-category pricing, one-click CSV chargeback export.

### 🤖 AI Ops Copilot — Query Layer for the Entire Platform
Not just an LLM integration — a purpose-built operator assistant that queries your live infrastructure in plain language. Ask *"which tenants are over quota?"*, *"show drift events from last week"*, or *"how many VMs are powered off on host X?"* and get live SQL-backed answers instantly. 40+ built-in intents with tenant / project / host scoping. Ollama backend keeps all data on your network; OpenAI / Anthropic available with automatic sensitive-data redaction.

### 🏢 Tenant Self-Service Portal *(v1.84.0+)*
A completely isolated, MFA-protected web portal that gives your customers read and restore access to their own infrastructure — without exposing your admin panel.

- **Security by design**: data isolated at the PostgreSQL Row-Level Security layer (not just application code); separate JWT namespace; IP-bound Redis sessions; per-user rate limiting.
- **7 self-service screens**: Dashboard, Infrastructure (VMs + disk + IPs + dependency graph), Snapshot Coverage (30-day calendar), Monitoring, Restore Center (side-by-side restore wizard — non-destructive), Runbooks (execute tenant-visible runbooks, dry-run, execution history), Activity Log (with username).
- **Controlled access**: opt-in per Keystone user; you define which OpenStack projects are visible; set expiry, MFA policy, and runbook visibility per customer.
- **Admin controls**: grant/revoke access, view active sessions, force-revoke, reset MFA, configure per-customer branding (logo, accent colour, portal title), review full audit log — all from the Admin → 🏢 Tenant Portal UI or REST API.
- **Kubernetes-native**: dedicated `nginx-ingress-tenant` Helm controller on its own MetalLB IP — TLS, WAF rules, and rate limits are isolated from the admin ingress.

> 📖 See the dedicated **[Tenant Portal Operator Guide](docs/TENANT_PORTAL_GUIDE.md)** for step-by-step setup, branding, MFA, and Kubernetes configuration.

---

## 🧪 Real Scenario — What a Day-2 Operator Actually Does

> *A tenant reports a critical VM is down. Here's what happens next with pf9-mngt:*

1. **Alert fires** — health score drops below 40 → auto-ticket created, team notified via Slack/email
2. **Diagnose** — Dependency Graph shows the VM's blast radius: which volumes, ports, and downstream services are affected
3. **Restore** — launch side-by-side restore: system reconstructs flavor, network, IPs, and credentials automatically; dry-run validates the plan first
4. **Verify** — new VM boots alongside the original; operator confirms, original deleted only after sign-off
5. **Audit** — full restore log: who triggered it, what mode, duration, outcome — auto-attached to the ticket
6. **Report** — SLA compliance report updated; metering records the restore operation for chargeback

*Total operator effort: decisions and approvals. The system handles the rest.*

> This same workflow applies to snapshot SLA breaches, drift events, capacity warnings, and tenant offboarding — all integrated, all audited.

---

## 🤔 Why Not Just Use Platform9, Scripts, or Grafana?

Because pf9-mngt combines in one system what would otherwise take 5+ separate tools:

| Problem | Typical approach | pf9-mngt |
|---------|-----------------|----------|
| Infrastructure inventory | Scripts → CSV dumps | Persistent PostgreSQL, 29 resource types, always yours |
| Snapshot scheduling | No native scheduler | Policy-driven, cross-tenant, quota-aware, SLA-compliant |
| VM restore | Manual reconstruction under pressure | Fully automated, two modes, dry-run, audited |
| VMware migration planning | Spreadsheets + guesswork | End-to-end: RVTools → risk scoring → wave planning → PCD provisioning |
| Operations governance | Separate ticketing + runbook tool | Built-in: 25 runbooks, full ticket lifecycle, approval gates, metering |

A custom script solves one problem once. pf9-mngt enforces operational discipline at scale.

> Full technical feature reference: [docs/FEATURES_REFERENCE.md](docs/FEATURES_REFERENCE.md)

---

## 🚀 Quick Start

### Prerequisites
- **Docker & Docker Compose** (for complete platform)
- **Python 3.11+** with packages: `requests`, `openpyxl`, `psycopg2-binary`, `aiofiles`
- **Valid Platform9 credentials** (service account recommended) — *not required in Demo Mode*
- **Network access** to Platform9 cluster and compute nodes — *not required in Demo Mode*

### 1. Complete Automated Setup (Recommended)
```powershell
# Clone repository
git clone https://github.com/erezrozenbaum/pf9-mngt.git
cd pf9-mngt

# Configure environment (CRITICAL: No quotes around values)
cp .env.template .env
# Edit .env with your Platform9 credentials

# One-command complete deployment
.\deployment.ps1

# What deployment.ps1 does:
# ✓ Checks/installs Docker Desktop
# ✓ Creates and validates .env configuration
# ✓ Creates required directories (logs, secrets, cache)
# ✓ Installs Python dependencies
# ✓ Builds and starts all Docker containers
# ✓ Initializes PostgreSQL database schema
# ✓ Configures LDAP directory structure
# ✓ Creates automated scheduled tasks
# ✓ Runs comprehensive health checks

# Alternative quick startup (assumes Docker installed)
.\startup.ps1

# Access services after deployment:
# UI:            http://localhost:5173
# API:           http://localhost:8000
# API Docs:      http://localhost:8000/docs
# Monitoring:    http://localhost:8001
# Database:      http://localhost:8080
```

### 1b. Kubernetes Deployment

For production environments, pf9-mngt ships a full Helm chart with ArgoCD GitOps support:

```powershell
# Add the Helm chart
helm repo add pf9-mngt https://erezrozenbaum.github.io/pf9-mngt
helm repo update

# Install with your values
helm install pf9-mngt pf9-mngt/pf9-mngt \
  --namespace pf9-mngt --create-namespace \
  -f k8s/helm/pf9-mngt/values.yaml \
  -f k8s/helm/pf9-mngt/values.prod.yaml

# Or use the supplied kustomize entrypoint
kubectl apply -k k8s/
```

> Full Kubernetes guide including Sealed Secrets, ArgoCD GitOps pipeline, MetalLB IP pools, and day-2 operations: **[docs/KUBERNETES_GUIDE.md](docs/KUBERNETES_GUIDE.md)**

### 1c. Demo Mode (No Platform9 Required)

Want to try the full system without a Platform9 environment? Demo mode populates the
database with realistic sample data (3 tenants, 35 VMs, 50+ volumes, snapshots,
drift events, compliance reports, etc.) and generates a static metrics cache.

```powershell
git clone https://github.com/erezrozenbaum/pf9-mngt.git
cd pf9-mngt

# The deployment wizard will ask "Production or Demo?" — choose 2 for Demo
.\deployment.ps1

# Or enable demo mode manually on an existing install:
#   1. Set DEMO_MODE=true in .env
#   2. python seed_demo_data.py          # populates DB + generates metrics cache
#   3. docker compose restart pf9_api    # API picks up DEMO_MODE env var
```

> In demo mode the UI shows an amber **DEMO** banner, the background metrics
> collector is skipped, and Platform9 credentials are not required.

### 2. Environment Configuration
```bash
# Platform9 Authentication
PF9_USERNAME=your-service-account@example.com
PF9_PASSWORD=your-secure-password
PF9_AUTH_URL=https://your-cluster.platform9.com/keystone/v3
PF9_USER_DOMAIN=Default
PF9_PROJECT_NAME=service
PF9_PROJECT_DOMAIN=Default
PF9_REGION_NAME=region-one

# Database
POSTGRES_USER=pf9
POSTGRES_PASSWORD=generate-secure-password-here
POSTGRES_DB=pf9_mgmt

# Monitoring
PF9_HOSTS=<HOST_IP_1>,<HOST_IP_2>,<HOST_IP_3>
METRICS_CACHE_TTL=60

# Production image version (docker-compose.prod.yml)
PF9_IMAGE_TAG=latest    # Pin to a release tag (e.g. v1.70.0) to lock images from ghcr.io
```

### 3. Manual Docker Setup
```bash
docker compose up -d
docker compose ps
docker compose logs pf9_api
```

### 4. Standalone Script Usage (No Docker Required)
```bash
# Inventory export
python pf9_rvtools.py

# Snapshot automation
python snapshots/p9_auto_snapshots.py --policy daily_5 --dry-run
python snapshots/p9_auto_snapshots.py --policy daily_5

# Compliance reporting
python snapshots/p9_snapshot_compliance_report.py --input latest_export.xlsx --output compliance.xlsx

# Policy assignment
python snapshots/p9_snapshot_policy_assign.py --config snapshots/snapshot_policy_rules.json --dry-run
```

---

## 🔧 Configuration

### Snapshot Policies
```bash
# Daily snapshots with 5-day retention
openstack volume set --property auto_snapshot=true \
                    --property snapshot_policies=daily_5 \
                    --property retention_daily_5=5 \
                    <volume-id>

# Multiple policies on one volume
openstack volume set --property auto_snapshot=true \
                    --property snapshot_policies=daily_5,monthly_1st \
                    --property retention_daily_5=5 \
                    --property retention_monthly_1st=12 \
                    <volume-id>
```

### Scheduler Worker (v1.62.0+)
```powershell
# Check scheduler status
docker logs pf9_scheduler_worker --tail 30

# Trigger metrics collection manually
docker exec pf9_scheduler_worker python host_metrics_collector.py --once

# Trigger RVTools collection manually
docker exec pf9_scheduler_worker python pf9_rvtools.py
```
> Metrics collection and RVTools inventory now run inside the `pf9_scheduler_worker` container automatically.
> No Windows Task Scheduler setup is required.

---

## 📁 Project Structure

```
pf9-mngt/
├── api/                          # FastAPI backend (170+ endpoints)
├── tenant_portal/                # Tenant self-service portal service (port 8010)
├── pf9-ui/                       # React 19 + TypeScript frontend
├── monitoring/                   # Prometheus metrics service
├── snapshots/                    # Snapshot automation engine
│   ├── p9_auto_snapshots.py      # Cross-tenant snapshot automation
│   ├── snapshot_service_user.py  # Service user management
│   ├── p9_snapshot_compliance_report.py
│   ├── p9_snapshot_policy_assign.py
│   └── snapshot_policy_rules.json
├── db/                           # PostgreSQL schema + migrations
├── backup_worker/                # Scheduled backup service
├── metering_worker/              # Resource metering service
├── search_worker/                # Full-text search indexer (Ops Assistant)
├── notifications/                # Email notification service
├── ldap/                         # OpenLDAP configuration
├── docs/                         # Full documentation suite
├── pf9_rvtools.py                # RVTools-style inventory export
├── host_metrics_collector.py     # Prometheus metrics collection
├── seed_demo_data.py             # Demo mode: populate DB + metrics cache
├── p9_common.py                  # Shared utilities
├── docker-compose.yml            # Full stack orchestration
├── deployment.ps1                # One-command deployment
├── startup.ps1                   # Quick start script
└── .env.template                 # Environment configuration template
```

---

## 📚 Documentation

| Document | Purpose |
|----------|---------|
| [Deployment Guide](docs/DEPLOYMENT_GUIDE.md) | Step-by-step deployment instructions |
| [Admin Guide](docs/ADMIN_GUIDE.md) | Day-to-day administration reference |
| [Architecture](docs/ARCHITECTURE.md) | System design, trust boundaries, data model, auth flow |
| [API Reference](docs/API_REFERENCE.md) | Complete API endpoint documentation |
| [Security Guide](docs/SECURITY.md) | Security model, authentication, encryption |
| [Security Checklist](docs/SECURITY_CHECKLIST.md) | Pre-production security audit checklist |
| [Restore Guide](docs/RESTORE_GUIDE.md) | Snapshot restore feature documentation |
| [Snapshot Automation](docs/SNAPSHOT_AUTOMATION.md) | Snapshot system design and configuration |
| [Snapshot Service User](docs/SNAPSHOT_SERVICE_USER.md) | Service user setup and troubleshooting |
| [VM Provisioning Setup](docs/DEPLOYMENT_GUIDE.md) | Includes `provisionsrv` service user setup (Runbook 2) |
| [Quick Reference](docs/QUICK_REFERENCE.md) | Common commands and URLs cheat sheet |
| [Kubernetes Deployment](docs/KUBERNETES_GUIDE.md) | Helm chart, ArgoCD GitOps, Sealed Secrets, day-2 ops |
| [Linux Deployment](docs/LINUX_DEPLOYMENT_GUIDE.md) | Running pf9-mngt on Linux instead of Windows |
| [Multi-Region & Multi-Cluster Guide](docs/MULTICLUSTER_GUIDE.md) | MSP operator guide: onboarding clusters, Region Selector UI, per-region filtering, workers, migration planning |
| [Support Ticket System Guide](docs/TICKET_GUIDE.md) | Full reference for the ticket lifecycle, API, SLA, email templates, and auto-tickets |
| [Tenant Portal Guide](docs/TENANT_PORTAL_GUIDE.md) | Tenant self-service portal: setup, branding, MFA, access management, Kubernetes deployment |
| [CI/CD Guide](docs/CI_CD_GUIDE.md) | CI pipeline, release process, and Docker image publishing |
| [Engineering Story](docs/ENGINEERING_STORY.md) | Platform9 evaluation background and the four operational gaps pf9-mngt solves |
| [Features Reference](docs/FEATURES_REFERENCE.md) | Complete technical deep-dive: auth, inventory, snapshots, restore, runbooks, tickets, copilot, migration planner |
| [Contributing](CONTRIBUTING.md) | Contribution guidelines |

---


## 🆘 Troubleshooting

Common issues and solutions are covered in [docs/ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md).

Quick commands:
- Container logs: `docker logs <container> --tail 50`
- Monitoring issues: `.\fix_monitoring.ps1`
- Force inventory sync: `docker exec pf9_scheduler_worker python pf9_rvtools.py`
- Database reset: `docker compose down -v && docker compose up -d`

---


## ❓ FAQ

**Q: Does this replace the Platform9 UI?** No — it is a complementary engineering console adding operational workflows not present in the native UI.

**Q: Is this an official Platform9 product?** No. Independent project, not endorsed by or affiliated with Platform9 Systems, Inc.

**Q: Can I try this without a Platform9 environment?** Yes — choose Demo Mode in `deployment.ps1` or set `DEMO_MODE=true` in `.env`.

**Q: Can I run this on Kubernetes?** Yes — fully supported since v1.82.0. See [docs/KUBERNETES_GUIDE.md](docs/KUBERNETES_GUIDE.md).

**Q: What are the minimum hardware requirements?** A Docker host with at least 4 GB RAM, 2 CPU cores, and network access to your Platform9 region endpoints.

For questions on authentication, RBAC, LDAP/AD, snapshots, and restore see [docs/ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md).

---


## 🕐 Recent Major Releases
### � Extended Forecasting, Cross-Region Intelligence & Anomaly Detection — v1.89.0

**[v1.89.0](CHANGELOG.md)** — Capacity engine extended with per-hypervisor compute forecasting and per-project quota-saturation forecasting (vCPUs, RAM, instances, floating IPs) including confidence scoring. New cross-region engine detects utilization imbalance, risk concentration, and growth-rate divergence across regions. New threshold-based anomaly engine fires on snapshot spikes, VM-count spikes, and API error spikes. Two new REST endpoints: `GET /api/intelligence/forecast` (on-demand runway per project/resource) and `GET /api/intelligence/regions` (per-region utilization + runway + growth). Intelligence Dashboard gains two tabs: Capacity Forecast and Cross-Region comparison. Department filter upgraded to prefix matching so insight subtypes are correctly routed. 524 unit tests pass, 0 HIGH bandit findings.

### �🩹 SLA Summary Route Hotfix + Insights Feed Tenant Column — v1.88.1

**[v1.88.1](CHANGELOG.md)** — Hotfix: `GET /api/sla/compliance/summary` was being shadowed by the earlier `GET /api/sla/compliance/{tenant_id}` route (FastAPI matches in registration order), causing the SLA Summary tab to always show empty even when tiers were configured. Fixed by reordering the routes. Also adds a Tenant/Project column to the Insights Feed table (from `metadata.project`), matching the column already present in Risk & Capacity. No DB migration required.
### � Phase 2 Intelligence — Recommendations, Bulk Actions, Copilot Intents — v1.88.0

**[v1.88.0](CHANGELOG.md)** — Phase 2 of Operational Intelligence: idle-VM waste insights now generate actionable recommendations (cleanup runbook ≥14 days, downsize suggestion ≥7 days). Risk engine auto-creates support tickets for snapshot-gap and critical health-decline insights. New bulk-acknowledge/bulk-resolve API endpoints. Five new Copilot natural-language intents (critical_insights, capacity_warnings, waste_insights, unacknowledged_insights_count, risk_summary). InsightsTab UI: SLA Summary shows only configured tenants sorted by breach status; Risk & Capacity gains Tenant/Project column; bulk-action bar above feed; per-row recommendations panel with dismiss. 524 unit tests pass, 0 HIGH bandit findings.

### �🩹 SLA & Intelligence Write 500 Hotfix — v1.87.2

**[v1.87.2](CHANGELOG.md)** — `PUT /api/sla/commitments` and intelligence write endpoints (acknowledge/snooze/resolve) all returned HTTP 500. Root cause: `require_permission()` returns `user.model_dump()` (a dict) but the affected handlers called `user.username` (attribute access). Fixed to `user["username"]` dict access in both `sla_routes.py` and `intelligence_routes.py`. 524 unit tests pass, 0 HIGH bandit findings.

### 🩹 Intelligence 500 Hotfix — v1.87.1

**[v1.87.1](CHANGELOG.md)** — All `GET /api/intelligence/` endpoints returned HTTP 500 after v1.87.0 deployed to Kubernetes. Root cause: `# nosec B608` bandit suppression comments placed on the same line as the opening triple-quoted f-string were included in the SQL text sent to PostgreSQL. PostgreSQL raised a syntax error on the `#` character, crashing every intelligence request. Fix: moved suppression comments to the `cur.execute(` call line. 524 unit tests pass, 0 HIGH bandit findings.

### 🔍 Department Workspaces + SLA Tier Modal — v1.87.0

**[v1.87.0](CHANGELOG.md)** — Operational Intelligence workspace selector: four context-aware workspaces (Global / Support / Engineering / Operations) filter the insight feed to relevant insight types with sensible severity presets; workspace preference persists to `localStorage`; `operator` role defaults to Engineering on first load. New `intelligence_utils.py` is the single source of truth for insight-type→department routing, consumed by `GET /api/intelligence/insights?department=` and `GET /api/intelligence/insights/summary?department=`. Fixed SLA tier assignment modal: `SlaTierTemplate` interface was using `id`/`name` but the API returns `tier`/`display_name` causing an empty dropdown; replaced bare KPI summary with a rich description block per tier (plain-language guidance, 3-column KPI grid, abbreviation legend). 538 tests, 0 HIGH bandit findings.

### 🔧 SLA Summary Hotfix — v1.86.2

**[v1.86.2](CHANGELOG.md)** — `InsightsTab` SLA Summary fix: API returns `{ summary, month }` but the component consumed `data.projects` (undefined), crashing on `.length`. Also corrected `SlaSummaryRow` interface and table columns to match the actual summary endpoint response (`tenant_id`/`tenant_name`/`breach_fields`/`at_risk_fields` instead of KPI values). 524 tests, 0 HIGH bandit findings.

### 🔧 Kubernetes Hotfix — v1.86.1

**[v1.86.1](CHANGELOG.md)** — K8s CrashLoopBackOff hotfix for `sla-worker` and `intelligence-worker`: Helm `values.yaml` was missing `redis.host` and `redis.port` keys. Both worker Deployments inject `REDIS_HOST`/`REDIS_PORT` via `{{ .Values.redis.host | quote }}` / `{{ .Values.redis.port | quote }}`, which resolved to empty strings when the keys were absent. `int("")` raised `ValueError: invalid literal for int() with base 10: ''` at startup. Fixed by adding `redis.host: pf9-redis` and `redis.port: "6379"` to `values.yaml`. Helm chart version bumped from `1.85.7` to `1.86.1`. 538 tests, 0 HIGH bandit findings.
### � SLA Compliance + Operational Intelligence — v1.86.0

**[v1.86.0](CHANGELOG.md)** — **SLA Compliance Tracking** and **Operational Intelligence Feed**: SLA tier templates (bronze/silver/gold/custom), per-tenant commitments, monthly KPI measurement (uptime %, RTO, RPO, MTTA, MTTR, backup success %), and PDF compliance reports. `sla_worker` computes KPIs every 4 hours; breach detection fires `sla_risk` insights. `intelligence_worker` (15-min poll) runs three engine families — **Capacity** (linear-regression storage trend), **Waste** (idle VMs, unattached volumes, stale snapshots), **Risk** (snapshot gap, health decline, unacknowledged drift). New `🔍 Insights` tab with three sub-views: Insights Feed (ack/snooze/resolve), Risk & Capacity, SLA Summary. Dashboard widget shows insight count by severity.

### �🔧 Tenant Portal Bug-Fixes — v1.85.5–v1.85.12

**[v1.85.12](CHANGELOG.md)** — K8s CrashLoopBackOff hotfix (tenant-ui nginx + monitoring httpx): `pf9-tenant-ui` crashed on v1.85.11 because `nginx.conf` hardcoded `proxy_pass http://tenant_portal:8010` (Docker Compose service name), which fails DNS resolution in Kubernetes (service is `pf9-tenant-portal`). Fixed using an envsubst template — same image works in Docker Compose (default `tenant_portal:8010`) and Kubernetes (`TENANT_PORTAL_UPSTREAM=pf9-tenant-portal:8010` via Helm). `pf9-monitoring` crashed because `_bootstrap_cache_from_api()` imports `httpx` at the function level (outside `try`) but `httpx` was absent from `monitoring/requirements.txt` — CI-built image raised `ModuleNotFoundError` on startup. Added `httpx==0.27.2`. 538 tests, 0 HIGH bandit findings.

**[v1.85.11](CHANGELOG.md)** — Tenant portal fully operational + branding logo + `[object Object]` error fix + Restore Center (MANUAL_IP / result panel / email): **Tenant portal was completely broken in production** — `tenant-ui` nginx had no proxy for `/tenant/*` so every API call returned `index.html`; fixed by adding `location /tenant/` proxy block. Branding logos uploaded via the admin UI (file-path `logo_url` in DB) now convert to inline base64 data URLs at read time — no nginx re-routing required. Admin UI no longer shows `[object Object]` on API validation errors (`apiFetch` in `pf9-ui` now unwraps FastAPI 422 array `detail` into readable messages). Restore Center gains `MANUAL_IP` network/IP strategy, post-restore result panel (new VM name, error details accordion), email summary button, and expandable history rows. Monitoring bootstrap always runs on startup. 538 tests, 0 HIGH bandit findings.

**[v1.85.10](CHANGELOG.md)** — K8s Branding/Monitoring/Runbook fixes: Branding save 422 fixed (logo URL validator now accepts server-relative `/api/` paths); logo upload 400 fixed in K8s (content-type extension fallback when nginx ingress strips multipart part headers); monitoring empty-hosts bug fixed (`""`.split(",")` = `[""]` → now correctly `[]`); monitoring startup race fixed (5× retry with 5 s gaps); `branding_logos` emptyDir volume added to K8s `pf9-api` pod; runbook results now include `items_scanned` counts and `summary` strings for operator visibility; SQL injection B608 fixed in `capacity_forecast` engine; 70 new tests (28 integration, 42 unit).

**[v1.85.9](CHANGELOG.md)** — Branding logo upload + monitoring docker-compose fixes: Admin Branding tab now has an **Upload Image** button with live preview (PNG/JPEG/GIF/WebP/SVG, ≤512 KB, per-tenant via `?project_id=`). Fixed 3 docker-compose bugs that caused "No metrics collected yet": wrong `MONITORING_SERVICE_URL` DNS name (`http://monitoring` → `http://pf9_monitoring`), `PF9_HOSTS` defaulting to `localhost` (prevents auto-discovery), missing `monitoring/cache` volume mount in `tenant_portal`. 35 new unit tests.

**[v1.85.8](CHANGELOG.md)** — Quota Usage / Runbooks VM picker / Monitoring host auto-discovery: Dashboard Quota bars now show real in-use figures (Nova/Cinder `?usage=true` was missing); `vm_health_quickfix` + `snapshot_before_escalation` Execute dialogs now show the Target VM dropdown (`server_id` field detected via `x-lookup: vms`); monitoring service auto-discovers hypervisor IPs from DB at startup when `PF9_HOSTS` is empty (new `/internal/prometheus-targets` admin API endpoint). 27 new unit tests.

**[v1.85.7](CHANGELOG.md)** — K8s bug-fix release: "Connection lost" banner on Branding tab eliminated (apiFetch now throws immediately on any HTTP error without retrying); `/tenant/quota` 400 fixed (CP ID regex now accepts slugs like `default`); snapshot calendar header labels realigned with cells + today marker added; Runbooks blank page / `TypeError` on `risk_level.toLowerCase()` fixed (normalised `apiExecuteRunbook` response + null guards); Monitoring empty-state now shows distinct message for service-unreachable vs no-data-collected.

**[v1.85.6](CHANGELOG.md)** — K8s bug-fix release: Active Sessions tab 500 fixed (Redis errors handled gracefully); Branding tab "branding_not_found" error banner fixed (detail string caught alongside HTTP 404); per-tenant branding overrides added (project-scoped rows, admin scope dropdown, `useBranding` re-fetches on login).

**[v1.85.5](CHANGELOG.md)** — K8s bug-fix release: Monitoring/Runbooks 401 fixed (added `/internal` to admin API RBAC exclusions); Volumes "Attached To" column shows VM name; VM list Coverage column populated; Fixed IP picker filters by selected network.

**[v1.85.4](CHANGELOG.md)** — K8s bug-fix release: VM Disk column now shows boot-volume size for BFV VMs; Volumes table shows last snapshot date; Monitoring/Runbooks 502 fixed by adding NetworkPolicy egress to admin API + monitoring pods; New VM Fixed IP picker shows IPs already in use in the selected network.

**[v1.85.3](CHANGELOG.md)** — Runbook execution from tenant portal (execute button, parameter form, dry-run toggle, execution history tab); Create VM: RFC-1123 name validation, fixed IP picker, cloud-init user/password; Dependency graph expanded to 5 node types (VM, Network, Subnet, Security Group, Volume) and 4 edge types; VM list and inventory CSV now include disk size and IP addresses; Activity Log shows username + truncated Keystone user ID; Dashboard correctly shows amber "Skipped" for skipped snapshot events.

---

### 🏢 Tenant Self-Service Portal — v1.84.0 → v1.84.19 *(Complete)*

**[v1.84.21](CHANGELOG.md)** — Fix `tenant-ui` build: `api.ts` had a second corrupted copy appended after the first clean copy (1341 lines instead of ~661) — prior replace_string_in_file left old interleaved fragments in place. Truncated file to first clean copy; Docker build now passes. **[v1.84.20](CHANGELOG.md)** — Fix `tenant-ui` build: `api.ts` was corrupted by overlapping replacements (code fragments interleaved, missing closing parens, unterminated template literals) → Docker `npm run build` failed with 10+ `TS1005`/`TS1160` errors. Rewrote file cleanly; `tsc --noEmit` passes. **[v1.84.19](CHANGELOG.md)** — Tenant portal crash-fix: `restore_jobs` table has no `region_id` column — 4 queries wrongly filtered by it → dashboard 500 `UndefinedColumn`; full `api.ts` adapter layer rewrite — all 16 API functions now unwrap backend `{key:[...],total:N}` envelopes and remap field names to match TypeScript interfaces, fixing `vms.filter is not a function` crash on every tenant screen. **[v1.84.18](CHANGELOG.md)** — DB/K8s fixes: `tenant_portal_role` had `INSERT` but not `SELECT` on `tenant_action_log` → every post-login endpoint returned 500; K8s secret password never set on DB user `tenant_portal_role` in `pf9-db-0` → login returned 500 immediately. **[v1.84.17](CHANGELOG.md)** — CI fix: `httpx` was missing from the integration test job `pip install` step; `test_tenant_portal_login_integration.py` imports it for live HTTP calls, causing `ModuleNotFoundError` at collection time and aborting the entire CI run. Added `httpx` to `.github/workflows/ci.yml`. **[v1.84.16](CHANGELOG.md)** — Fix K8s 504: NetworkPolicy ingress namespace was `ingress-nginx` but nginx-tenant controller deploys to `ingress-nginx-tenant`; egress had no Keystone (443/5000) rule; login error banner now shows context-aware messages (was always "Invalid credentials" for any error including 504/403). **[v1.84.15](CHANGELOG.md)** — Fix 504 on tenant portal login: async Keystone call (was blocking uvicorn event loop); `VITE_TENANT_API_TARGET` added to docker-compose override (dev proxy was hitting localhost inside container); K8s ingress proxy-read/connect-timeout annotations added. **[v1.84.14](CHANGELOG.md)** — Domain field on login form (Keystone multi-domain support); `domain` field hardened with `max_length` + regex whitelist; security tests extended to S33. **[v1.84.13](CHANGELOG.md)** — Bug-fix & security hardening: `log_auth_event` TypeError crash on every access grant/revoke fixed; Audit Log sub-tab 500 (wrong column names) fixed; batch grant transaction-poisoning fixed (savepoints); stored-XSS via `javascript:` / `data:` URIs in branding URLs blocked; field length limits added; security test suite extended to S30. **[v1.84.12](CHANGELOG.md)** — Grant Access wizard (3-step: tenant picker → user checkboxes → MFA/notes); batch grant API; CP dropdown. **[v1.84.11](CHANGELOG.md)** — Grant Access form gains User Name + Tenant/Org Name fields; access table shows friendly labels; `user_name`/`tenant_name` DB + API. **[v1.84.10](CHANGELOG.md)** — Nav fix: `tenant_portal` tab now appears in Admin Tools; DB migration for live environments; guide corrections. **[v1.84.9](CHANGELOG.md)** — Tenant Portal complete: `GET /tenant/branding` unauthenticated branding endpoint (60 s cache); admin `GET/PUT /branding/{cp_id}` and `DELETE /mfa/{cp_id}/{user_id}` endpoints; Admin UI "🏢 Tenant Portal" tab with 4 sub-tabs; 27 P8 security tests (S01–S27 across 8 categories). → [Tenant Portal Guide](docs/TENANT_PORTAL_GUIDE.md)

**[v1.84.4](CHANGELOG.md)** — Tenant-ui SPA: React + TypeScript, 7 screens (Dashboard, Infrastructure, Snapshot Coverage, Monitoring, Restore Center, Runbooks, Activity Log), MFA login, per-customer branding. Kubernetes stability fixes in v1.84.5–v1.84.8 (dedicated `nginx-ingress-tenant` on separate MetalLB IP).

**[v1.84.3](CHANGELOG.md)** — Full restore center (6 endpoints), TOTP + email OTP + backup-code MFA, audit logging on all tenant endpoints, ops Slack/Teams + tenant email notifications.

**[v1.84.0](CHANGELOG.md)** — Tenant Self-Service Portal foundation: `tenant_portal_role` with RLS on 5 inventory tables; 5 schema tables; isolated FastAPI on port 8010 (JWT `role=tenant`, Redis sessions, IP binding, per-user rate limiting); 6 admin API endpoints; Helm NetworkPolicy.

---

### 🌍 Multi-Region & Multi-Cluster Support — v1.73.0 → v1.79.0

**[v1.79.0](CHANGELOG.md)** — External LDAP / AD identity federation with group-to-role mapping, credential passthrough, and sync worker.

**[v1.76.0](CHANGELOG.md)** — Multi-region management UI: `RegionSelector` nav dropdown, `ClusterManagement` admin panel (add/delete/test/discover CPs and regions), per-region filtering across all views.

**[v1.73.0](CHANGELOG.md)** — Full multi-cluster infrastructure: ClusterRegistry, per-region worker loops, cross-region migration planning, SSRF protection, health tracking.

---

### 🎫 Support Ticket System — v1.58 → v1.60

**[v1.60](CHANGELOG.md)** — Ticket analytics, bulk actions, LandingDashboard KPI widget, metering and runbook ticket integration.

**[v1.58](CHANGELOG.md)** — Full ticket lifecycle: 5 types, SLA daemon, 35+ endpoints, auto-ticket triggers (health score, drift, graph deletes, runbook failures), approval workflows, email templates.

---

*Security hardening, performance, CI fixes, and UI polish are documented in the full changelog.*

> Complete version history for all releases: [CHANGELOG.md](CHANGELOG.md)

---

## 👥 Who This Is For

- **MSPs running multi-tenant Platform9 environments** — multi-region console, per-customer chargeback, SLA enforcement, automated tenant onboarding and offboarding
- **Enterprise OpenStack teams** — operational governance, snapshot compliance, capacity planning, VMware migration tooling
- **Engineering teams responsible for Day-2 operations** — not provisioning, but everything that comes after it

---

## ❌ When NOT to Use pf9-mngt

- **You manage a single small tenant with no SLA requirements** — the native Platform9 UI is sufficient
- **You don't need automation or governance** — if manual workflows are acceptable at your scale, this is over-engineered for you
- **Your team doesn't own Day-2 operations** — if Platform9 SaaS handles everything and you never touch restore, compliance, or chargeback, you don't need this layer
- **You want a Platform9-supported product** — pf9-mngt is independent and community-maintained, not an official Platform9 offering

If any of the above applies, save yourself the setup. If they don't — this is built for you.

---

## 🎯 Positioning

pf9-mngt is:

- ❌ Not a UI replacement — it is an engineering console that adds workflows the native Platform9 UI does not provide
- ❌ Not a cloud control plane — it orchestrates Platform9 / OpenStack via their existing APIs
- ❌ Not a provisioning tool — it operates on what has already been provisioned
- ✅ The **operational layer on top** — what you reach for when something breaks, needs auditing, or must be tracked at scale

---

## 🤝 Contributing

Contributions are welcome — code, documentation, bug reports, feature suggestions, or feedback.

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on:
- How to report bugs
- How to suggest features
- How to submit pull requests
- Development setup and coding standards

---

## 💝 Support the Project

If pf9-mngt saves your team time, consider:

- ⭐ **Star the repository** — helps others discover the project
- 🐛 **Report bugs** — open an issue
- 💻 **Contribute code** — PRs are welcome
- 💬 **Share feedback** — what would you add?

### ☕ Buy Me a Coffee

If this project saves you time or makes your Platform9 operations easier, you can support its continued development:

<a href="https://buymeacoffee.com/erezrozenbaum" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" width="200"></a>

---

## 👤 About the Creator

**Erez Rozenbaum** — Cloud Engineering Manager & Original Developer

Built as part of a serious Platform9 evaluation to solve real operational gaps for MSP and enterprise teams. 422+ commits, 121 releases, 16 containerized services, 170+ API endpoints — built alongside regular responsibilities.

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

**Copyright © 2026 Erez Rozenbaum and Contributors**

---

**Project Status**: Production Ready | **Tests**: 524 passed, 22 skipped | **Version**: 1.88.1 | **Last Updated**: April 2026
