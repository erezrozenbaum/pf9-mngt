# pf9-mngt

<p align="center">
  <strong>Operational Control Plane for Platform9 / OpenStack</strong><br>
  Visibility &nbsp;·&nbsp; Automation &nbsp;·&nbsp; Recovery &nbsp;·&nbsp; Governance &nbsp;·&nbsp; Multi-Region Control
</p>

<p align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.82.33-blue.svg)](CHANGELOG.md)
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

One system. No duct tape.

---

## 🧭 In One Sentence

pf9-mngt is an operational control plane for Platform9/OpenStack that gives you:

- **Full infrastructure visibility** across all tenants and regions — all metadata owned by you, not the platform
- **Automated snapshot & restore workflows** — no native equivalent exists in Platform9 or OpenStack
- **VMware → OpenStack migration planning** — end-to-end from RVTools ingestion to PCD auto-provisioning
- **Governance, audit, and Day-2 tooling** — runbooks, tickets, metering, and chargeback

All in one self-hosted engineering console that works alongside Platform9 via its APIs.

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

These are **Day-2 operations problems**. pf9-mngt solves them.

---

## 💡 What pf9-mngt Is

A self-hosted operational platform that **extends** Platform9 / OpenStack — not replaces it.

- A **persistent inventory engine** — all Platform9 / OpenStack metadata in your own PostgreSQL, always available, independent of platform uptime (the RVTools equivalent for OpenStack)
- A **snapshot automation engine** — no native scheduler exists in Platform9 or OpenStack; this one is quota-aware, cross-tenant, policy-driven, with SLA compliance reporting
- A **VM restore system** — full automation of flavor, network, IPs, credentials, and volumes; two modes (side-by-side and replace); no native equivalent exists in OpenStack
- A **migration planning workbench** — from RVTools ingestion through cohort design, wave planning, and PCD auto-provisioning
- A **unified engineering console** — 30+ management tabs, RBAC, metering, chargeback, runbooks, tickets, and AI Ops Copilot

✔ Works alongside Platform9 via its APIs &nbsp;·&nbsp; ❌ Not a UI replacement &nbsp;·&nbsp; ❌ Not an official Platform9 product

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

**16-container microservices platform:**

| Service | Stack | Port | Purpose |
|---------|-------|------|---------|
| **nginx (TLS proxy)** | nginx:1.27-alpine | 80/443 | HTTPS termination, HTTP→HTTPS redirect, reverse proxy to API and UI |
| **Frontend UI** | React 19.2+ / TypeScript / Vite | 5173 | 30+ management tabs + admin panel |
| **Backend API** | FastAPI / Gunicorn / Python | 8000 | 170+ REST endpoints, RBAC middleware, 4 workers + --max-requests 1000 |
| **Redis** | redis:7-alpine | internal | OpenStack inventory/quota cache (60–300 s TTL, allkeys-lru, 128 MiB cap) |
| **LDAP Server** | OpenLDAP | internal | Enterprise authentication directory (not exposed to host) |
| **LDAP Admin** | phpLDAPadmin | 8081 *(dev profile)* | Web-based LDAP management (`--profile dev`) |
| **Monitoring Service** | FastAPI / Python | 8001 | Real-time metrics via Prometheus |
| **Database** | PostgreSQL 16 | internal | 65+ tables, audit, metering, migration planner (not exposed to host) |
| **Database Admin** | pgAdmin4 | 8080 *(dev profile)* | Web-based PostgreSQL management (`--profile dev`) |
| **Snapshot Worker** | Python | — | Automated snapshot management |
| **Notification Worker** | Python / SMTP | — | Email alerts for drift, snapshots, compliance |
| **Backup Worker** | Python / PostgreSQL | — | Scheduled DB + LDAP backups to NFS, restore *(backup profile)* |
| **Scheduler Worker** | Python | — | Host metrics collection + RVTools inventory (runs inside Docker) |
| **Metering Worker** | Python / PostgreSQL | — | Resource metering every 15 minutes |
| **Search Worker** | Python / PostgreSQL | — | Incremental full-text indexing for Ops Assistant |
| **LDAP Sync Worker** | Python / PostgreSQL / OpenLDAP | — | Bi-directional DB ↔ LDAP sync, polls every 30 s |

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
| Runbooks (25 built-in, dept visibility, approval workflows) | ✅ Production |
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
| Tenant Self-Service Portal | ⬜ Planned |

---


## 🧭 Why This Was Built

Built during a serious Platform9 evaluation — stress-testing real operational workflows revealed four gaps no native tooling covered: **metadata ownership** (no RVTools-equivalent for OpenStack), **VM restore** (no native workflow exists), **snapshot automation** (no native scheduler), and **VMware migration planning** (no native RVTools → PCD workflow).

Rather than pause the evaluation, we solved them. The result is pf9-mngt — 409+ commits, 121 releases, built using AI as a genuine engineering partner alongside regular responsibilities.

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

### 1b. Demo Mode (No Platform9 Required)

Want to try the portal without a Platform9 environment? Demo mode populates the
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
#   3. docker-compose restart pf9_api    # API picks up DEMO_MODE env var
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
docker-compose up -d
docker-compose ps
docker-compose logs pf9_api
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
├── api/                          # FastAPI backend (155+ endpoints)
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
- Database reset: `docker-compose down -v && docker-compose up -d`

---


## ❓ FAQ

**Q: Does this replace the Platform9 UI?** No — it is a complementary engineering console adding operational workflows not present in the native UI.

**Q: Is this an official Platform9 product?** No. Independent project, not endorsed by or affiliated with Platform9 Systems, Inc.

**Q: Can I try this without a Platform9 environment?** Yes — choose Demo Mode in `deployment.ps1` or set `DEMO_MODE=true` in `.env`.

**Q: Can I run this on Kubernetes?** Yes — fully supported since v1.82.0. See [docs/KUBERNETES_GUIDE.md](docs/KUBERNETES_GUIDE.md).

**Q: What are the minimum hardware requirements?** A Docker host with at least 4 GB RAM, 2 CPU cores, and network access to your Platform9 region endpoints.

For questions on authentication, RBAC, LDAP/AD, snapshots, and restore see [docs/ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md).

---


## 🕐 Latest Release

**[v1.82.33](CHANGELOG.md)** — Monitoring pod restart loop hotfix: `TrustedHostMiddleware` removed from `monitoring/main.py` — it blocked Kubernetes kubelet health probes.

> Full version history for all 121 releases: [CHANGELOG.md](CHANGELOG.md)

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

## 🔥 What Makes It Different

Most platforms solve provisioning.

pf9-mngt solves **what happens after deployment** — the snapshot SLAs that must hold, the 3am restore that must succeed, the compliance report due tomorrow, the capacity forecast before the cluster fills up, the VMware migration that has to go right.

Built from real-world operations. 409+ commits, 121 releases, 16 containerized services.

Not theory — from what actually breaks in production.

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

**Project Status**: Production Ready | **Version**: 1.82.33 | **Last Updated**: March 2026
