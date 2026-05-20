# PF9 Management — Day-2 Operations Control Plane

> **Platform9 solves provisioning. pf9-mngt solves Day-2 operations at scale.**

**pf9-mngt** is a self-hosted operational control plane that **extends Platform9/OpenStack** with persistent inventory, automated recovery workflows, and governance capabilities. Built for teams responsible for what happens *after* Day-0 provisioning.

*Platform9 handles infrastructure provisioning brilliantly. pf9-mngt handles what comes next — snapshot SLA enforcement, 3am VM restores under pressure, cross-tenant visibility at scale, and VMware migration planning.*

**Works alongside Platform9 via its APIs — not a replacement, but an operational layer on top.**

![Dashboard Overview](docs/images/dashboard-overview.png)

![Architecture Overview](docs/images/Architecture.png)

## ⚡ What You'll See in 60 Seconds
• 🎯 **Multi-tenant dashboard** with live KPIs and health metrics  
• 📊 **Snapshot compliance** across 3 demo tenants with SLA tracking
• 🔄 **VM restore workflow with side-by-side validation**  
• 🗺️ **Migration planner** with RVTools import and risk assessment

---

## 🎯 Who This Is For

- **🏢 MSPs** managing Platform9/OpenStack environments
- **☁️ Cloud Providers** operating multi-tenant infrastructure  
- **⚙️ DevOps Teams** requiring automated Day-2 operations

*These operational challenges require purpose-built tooling beyond standard platform capabilities.*

## 🚀 Quick Facts

• **🏗️ 18-container microservices** — designed for production deployment  
• **📈 670+ commits, actively evolving** — established codebase  
• **✅ 593 passing tests** — comprehensive test coverage ([see tests/](tests/))  
• **🔒 Kubernetes-native** — Helm charts + ArgoCD GitOps  
• **🎮 Demo mode** — full product experience without Platform9  

[![Version](https://img.shields.io/badge/version-2.5.0-blue.svg)](CHANGELOG.md) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) [![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://www.docker.com/) [![Kubernetes](https://img.shields.io/badge/kubernetes-ready-green.svg)](https://kubernetes.io/)

*Used to model real-world MSP Day-2 operational scenarios.*

---

## 🔄 The Day-2 Operations Reality

Provisioning is not the hard part anymore. Running infrastructure at scale is.

What actually breaks in real Platform9/OpenStack environments:
- **Snapshot SLAs** across tenants — no native scheduler exists
- **VM restore under pressure** — no native workflow; everything is manual reconstruction  
- **Metadata ownership** — resource names, relationships, and topology live on the platform, not with you
- **Cross-tenant visibility** at scale — the native UI is per-tenant, not operational-aggregate
- **Customer self-service** — tenants need infrastructure status without you being a human API

---

## 🔄 Three Core Workflows

### 1. 📸 Snapshot SLA Enforcement  
**Policy Definition** → **Automated Execution** → **Compliance Monitoring** → **Alert Generation** → **Audit Reports**

### 2. 🔄 VM Restore Under SLA Pressure  
**Select Target VM** → **Dry-Run Validation** → **Execute Restore** → **Real-time Monitoring** → **Compliance Audit**

### 3. 🗺️ Migration Planning & Execution  
**RVTools Import** → **Risk Assessment** → **Cohort Analysis** → **Wave Planning** → **PCD Deployment**

---

## 🏛️ Four Operational Pillars

Everything in pf9-mngt is built around four operational concerns:

| Pillar | What it covers |
|--------|---------------|
| 🔍 **Visibility** | Cross-tenant, multi-region inventory with drift detection, dependency graph, and historical tracking — metadata owned by you, not the platform |
| 🔄 **Recovery** | Snapshot automation and full VM restore orchestration — two modes, dry-run validation, SLA compliance, not natively addressed in OpenStack |
| ⚙️ **Operations** | Ticketing, 25 built-in runbooks, metering, chargeback, standardized governance workflows, and tenant self-service portal |
| 🧠 **Intelligence** | AI Ops Copilot (plain-language queries against live infrastructure), Operational Intelligence Feed (capacity, waste, risk and anomaly engines), **Workload Right-Sizing** (idle + over-provisioned VM detection with flavor recommendations and savings estimates), SLA compliance tracking, QBR PDF generator, Account Manager Portfolio and Executive Health dashboards, revenue leakage detection |

> Everything else in the system — LDAP, multi-region, Kubernetes, export reports — supports one of these four pillars.

---

## 🎯 What This Actually Replaces

| **Without pf9-mngt** | **With pf9-mngt** |
|----------------------|-------------------|
| Scripts that dump inventory to CSV, manually maintained | Persistent PostgreSQL inventory, 29 resource types, always current |
| VM restore = manual reconstruction at 3am under SLA pressure | Fully automated restore — flavor, network, IPs, volumes, credentials |
| No snapshot scheduler — custom cron per tenant, no SLA tracking | Policy-driven snapshot automation, cross-tenant, quota-aware, SLA-compliant |
| Migration planning in spreadsheets — guesswork | End-to-end planner: RVTools → risk scoring → wave planning → PCD provisioning |
| Separate ticketing tool + separate runbook wiki + separate billing exports | Built-in: tickets, 25 runbooks, metering, chargeback — one system |
| Tenants call you for every status check — your team is the bottleneck | Tenant self-service portal: customers view their own VMs, snapshots, restores — scoped, isolated, MFA-protected |
| Idle and over-provisioned VMs burning budget silently | Workload Right-Sizing: automated idle/over-provisioned VM detection, flavor recommendations, monthly savings estimates — surfaced for both admins and tenants |

**Unified operational platform.**

---
## 🎯 What Makes It Different

Most platforms solve provisioning. pf9-mngt solves **what happens after deployment** — snapshot SLAs, restore procedures, compliance reporting, capacity forecasting, and migration planning.

**MSP Business Value:**
- **SLA compliance tracking** per tier (Gold/Silver/Bronze) with automated breach detection
- **QBR PDF generation** per customer with usage analytics and capacity planning
- **Account Manager Portfolio dashboard** — per-tenant SLA status, vCPU usage, leakage alerts
- **Executive Health dashboard** — fleet SLA gauge, MTTR, revenue leakage detection
- **Revenue leakage detection** — identify underutilized resources and optimization opportunities
- **Workload Right-Sizing** (v2.6.0) — automatically classify idle and over-provisioned VMs, recommend smaller flavors, and quantify estimated monthly savings; surfaces in both admin UI and tenant self-service portal with Snooze/Dismiss lifecycle management

Built from real-world operational scenarios observed during Platform9 evaluation.

---
## 📊 Why This Matters

| **Challenge** | **Native Platform9** | **pf9-mngt Solution** |
|---------------|---------------------|----------------------|
| Cross-tenant visibility | Per-tenant only | Centralized persistent inventory (29 resource types) |
| Snapshot SLA enforcement | None built-in | Policy-driven, multi-tenant, audited |
| VM restore workflow | Manual reconstruction | Full automation, two modes, dry-run validation |
| Metadata ownership | Lives on the platform | Your PostgreSQL, always available |
| Tenant self-service | You are the human API | MFA-protected portal, RLS-isolated, scoped to their projects |
| VMware migration | No native tooling | End-to-end planner: RVTools → PCD provisioning |

---

## 🚀 Demo Mode

⏱ **Setup time:** ~2–3 minutes  
🧠 **No Platform9 required**  
🎯 **Full product experience**  

```bash
git clone https://github.com/erezrozenbaum/pf9-mngt.git
cd pf9-mngt
.\deployment.ps1  # Choose option 2 for Demo Mode
```

**Experience:** Dashboard + compliance tracking + VM restore + migration planning + chargeback  
**Ready-to-use demo data** with tenants, VMs, snapshots, and SLA scenarios

---

## 🚀 Quick Start

### 🐳 Complete Platform (Recommended)
```bash
git clone https://github.com/erezrozenbaum/pf9-mngt.git
cd pf9-mngt
.\deployment.ps1  # Automated setup wizard

# Access: http://localhost:5173 (UI) | http://localhost:8000 (API)
```

### ☁️ Kubernetes Production
```bash
helm repo add pf9-mngt https://erezrozenbaum.github.io/pf9-mngt
helm install pf9-mngt pf9-mngt/pf9-mngt \
  --namespace pf9-mngt --create-namespace \
  -f k8s/helm/pf9-mngt/values.prod.yaml
```

---

## 🏗️ Architecture

**Production-ready microservices platform** with 18 specialized containers:

| Service Type | Count | Examples | Stack |
|--------------|-------|----------|-------|
| **Core Services** | 6 | Frontend UI, Backend API, Database, Monitoring, Tenant Portal, Cache | React 19.2+, FastAPI, PostgreSQL 16 |
| **Worker Services** | 9 | Snapshot, Backup, Metering, Search, Sync Workers | Python |
| **Infrastructure** | 3 | Nginx, Redis, Queue Manager | Standard components |

**What sets it apart:**
- **Persistent inventory engine** — 29 resource types, independent of platform uptime (RVTools-equivalent for OpenStack)
- **Snapshot automation engine** — quota-aware, cross-tenant, policy-driven scheduling
- **VM restore system** — full automation of flavor, network, IPs, credentials, volumes
- **Migration planning workbench** — from RVTools ingestion through PCD auto-provisioning

**Tech Stack:** React 19.2+ / TypeScript / FastAPI / PostgreSQL 16 / Redis / Docker / Kubernetes  
**Deployment Ready:** 593 tests, security scanning, observability, Kubernetes deployment  
*Built to solve operational gaps identified during Platform9 evaluation.*

---

## 📸 Key Screens

**Dashboard Overview** — Multi-tenant health metrics and live KPIs  
![Landing Dashboard](docs/images/dashboard-overview.png)

**Snapshot Compliance** — SLA tracking and automated remediation  
![Snapshot Compliance](docs/images/snapshot-compliance-report.png)

**Tenant Self-Service Portal** — Isolated MFA-protected interface  
![Tenant Portal](docs/images/Tenant_portal.png)

**Chargeback & Metering** — Multi-resource cost tracking  
![Metering & Chargeback](docs/images/Metering_system.png)  

---

## 🎬 Video Walkthrough

▶️ [**PF9 Management System — Full UI Walkthrough (15 min)**](https://www.youtube.com/watch?v=V0z5-HKVWts)

---

## 📚 Documentation

| Document | Purpose |
|----------|---------|
| [Deployment Guide](docs/DEPLOYMENT_GUIDE.md) | Step-by-step setup instructions |
| [Admin Guide](docs/ADMIN_GUIDE.md) | Day-to-day administration |
| [Migration Planner Guide](docs/MIGRATION_PLANNER_GUIDE.md) | VMware → PCD migration planning, provisioning & handoff |
| [Architecture](docs/ARCHITECTURE.md) | System design & data model |
| [Kubernetes Guide](docs/KUBERNETES_GUIDE.md) | Helm charts & production deployment |
| [Features Reference](docs/FEATURES_REFERENCE.md) | Complete technical deep-dive |

---
## 📋 Current Status & Maturity

| Component | Status | Notes |
|-----------|--------|---------|
| **Demo Mode** | ✅ Fully available | Complete experience, no Platform9 required |
| **Platform9 Integration** | ✅ Supported | Works via Platform9 APIs, tested against v6.0+ |
| **Kubernetes Deployment** | ✅ Helm/ArgoCD ready | Production-ready manifests, observability included |
| **Test Coverage** | ✅ 593 passing tests | API, integration, and UI tests ([see tests/](tests/)) |
| **Production Usage** | ✅ Production-ready core | 593 tests, Kubernetes deployment, enterprise monitoring |
| **Documentation** | ✅ Complete | 20+ guides covering deployment through operations |

*Production-ready architecture; currently used in evaluation and laboratory environments.*

---
## 🤝 How This Complements Platform9

**Platform9 excels at infrastructure provisioning.** pf9-mngt extends it with operational capabilities:

| **Challenge** | **Platform9 Strength** | **pf9-mngt Extension** |
|---------------|------------------------|------------------------|
| Infrastructure deployment | ✅ Excellent provisioning APIs | Persistent inventory, 29 resource types, historical tracking |
| Basic operations | ✅ Native OpenStack workflows | Automated snapshot scheduling, SLA compliance, audit trails |
| VM management | ✅ Standard create/delete | Full restore automation, dry-run validation, side-by-side comparison |
| Multi-tenancy | ✅ Keystone project isolation | Cross-tenant operational visibility, centralized governance |
| Migration support | ✅ Standard OpenStack migration | End-to-end VMware migration planning: RVTools → PCD provisioning |
| Operational workflow | ✅ Admin UI for infrastructure | Tenant self-service portal, ticketing, runbooks, chargeback |

**Works alongside Platform9 via its APIs. Better together.**

---

## ❓ FAQ

**Q: Does this replace the Platform9 UI?**  
No — it's a complementary operational layer. Platform9 handles provisioning, pf9-mngt handles Day-2 operations.

**Q: Can I try without Platform9?**  
Yes — Demo Mode provides full functionality with sample data.

**Q: Is this production-ready?**  
Designed for production deployment — 593 tests ([see tests/](tests/)), Kubernetes deployment, security scanning, observability.

**Q: Minimum requirements?**  
Docker host: 4GB RAM, 2 CPU cores, network access to Platform9 endpoints.

---
## 💰 MSP ROI Impact

**For Service Providers, Every Feature Drives Revenue:**

| **MSP Challenge** | **Revenue Impact** | **pf9-mngt Solution** |
|-------------------|-------------------|----------------------|
| **Revenue Leakage** | Lost $2-5K/month per client from untracked resources | Automated leakage detection with efficiency scoring |
| **Manual Tenant Support** | $50-200/ticket for status checks and restores | Self-service tenant portal eliminates 80%+ of tickets |
| **Compliance Penalties** | $10-50K per SLA breach incident | Automated SLA monitoring with proactive breach prevention |
| **Migration Risk** | $25-100K+ in failed migration costs | End-to-end VMware migration planner with risk scoring |
| **Billing Disputes** | Hours/month of manual reconciliation | Multi-currency chargeback system with audit trails |
| **Executive Reporting** | Manual QBR preparation (4-8 hours/client) | Automated QBR PDF generation per customer |

**Typical MSP ROI:** 300-500% within 6 months through reduced operational overhead and eliminated revenue leakage.

*Estimates based on common MSP operational cost patterns; actual results depend on environment size and processes.*

---
## 🆕 Recent Highlights

- **v2.6.7** — Bug fix: VM provisioning batch failed immediately on execute; `get_provisioner_client()` bypasses `Pf9Client.__init__` so the `_cb` circuit-breaker attribute was never set, causing `AttributeError` in `_cb_request()` on every provisioning attempt (May 2026)
- **v2.6.6** — Admin Right-Sizing & Cost Waste page: each recommendation card now has a **🎫 Open Ticket** button that creates a support ticket via `/api/tickets/_auto`, pre-filled with VM details, routed to Tier3 Support, with deduplication (`auto_source=admin_rightsizing`) (May 2026)
- **v2.6.5** — Tenant "Request Resize" now auto-creates a tracked internal support ticket (routed to `Tier3 Support` by default) and sends an ops team notification email via the `rightsizing_request` template; replaces standalone email to `support_email` branding field; ticket deduplication prevents duplicate tickets for repeated clicks; new `/internal/tickets/auto` endpoint for cross-service ticket creation (May 2026)
- **v2.6.4** — Right-Sizing billing impact display (monthly cost + projected savings in configured currency) for both admin and tenant portal; admin project dropdown filter; tenant "Request Resize" CTA; fixed `tenant_portal_role` missing `UPDATE` grant on `rightsizing_recommendations` and `SELECT` grant on `metering_flavor_pricing` (May 2026)
- **v2.6.3** — Bug fix: Right-Sizing & Cost Optimisation showed zero data despite idle VMs visible in Insights; metering worker API fallback was calling `/monitoring/vm-metrics` unauthenticated (401), falling back to a path that sets `cpu_usage_percent = NULL`; now uses `/internal/monitoring/vm-metrics` with `X-Internal-Secret` (May 2026)
- **v2.6.2** — Bug fix: tenant portal Cost Optimisation screen returned 500 (`inject_rls_vars` called with connection instead of cursor); Right-Sizing nav item now seeded into navigation DB on fresh deploy (May 2026)
- **v2.6.1** — Bug fix: `RightsizingEngine` loader methods (`_load_cost_model`, `_load_flavors`, `_load_flavor_pricing`) now rollback the shared DB connection on exception, preventing a transaction abort cascade that caused `_compute_vm_stats` to silently return no data (May 2026)
- **v2.6.0** — Workload Right-Sizing & Cost Waste Detection: automated classification of idle and over-provisioned VMs, flavor recommendations, monthly savings estimates, and Snooze/Dismiss lifecycle; surfaced in both the admin UI (new Right-Sizing tab) and tenant portal (new Cost Optimisation screen) (May 2026)
- **v2.5.0** — Circuit breaker state surfaced in region sync-status endpoint (`circuit_breaker.state`, `failure_count`, `open_for_seconds_remaining`); live observability for outbound Platform9 API connection health (May 2026)
- **v2.4.0** — Notification dead-letter queue: failed email sends are now retried with exponential back-off (5 → 15 → 60 min) instead of being silently dropped; notifications exhausting all retries are marked `dead_lettered`. New `GET /notifications/admin/retry-queue` endpoint provides queue visibility (May 2026)
- **v2.3.4** — Bug fix: runbook billing-gate credentials were silently failing to decrypt (wrong Fernet key); fixed to use `integration_key` secret via `crypto_helper`. QBR download auth updated from stale localStorage header to httpOnly cookie (May 2026)
- **v2.3.3** — SSRF guard added to external integrations `base_url` validation: private/loopback/link-local raw-IP targets are now rejected at the Pydantic model layer on create and update (May 2026)
- **v2.3.2** — Migration wave execution timeline (started/completed timestamps, duration column), wave completion email/webhook notifications, automatic resolution of migration-in-progress operational insights, migrations completed column in SLA compliance history, Migration Activity section in QBR PDFs (May 2026)
- **v2.3.0** — Configurable health score weights (UI settings panel), per-tenant health score disable toggle, health score breakdown card + trend sparkline; snapshot chain tracking with parent linkage, pre-delete guard trigger, chain policy editor, and Snapshot Chain Explorer UI; per-worker PostgreSQL roles (least-privilege GRANTs); region circuit breaker for OpenStack API calls; Alembic migration framework (May 2026)
- **v2.2.0** — Copilot agentic execution: "Run it" button lets operators trigger runbooks directly from the Copilot chat, with per-user hourly quota, platform-wide disable toggle, dry-run mode, risk-level badges, and full audit trail (May 2026)
- **v2.1.0** — Tenant-facing notification subscriptions (9 event types, email + SSRF-protected webhook delivery); admin-configurable MFA enrollment enforcement for admin and superadmin roles (May 2026)
- **v1.99.0** — PgBouncer connection pooling (transaction mode, pool_size=20) for all services; tenant composite health scoring (0–100) across snapshot compliance, quota headroom, drift, SLA tier, and open tickets — auto-computed every 4h with operational insight generation on low scores (May 2026)
- **v1.98.0** — Fernet key rotation CLI; billing webhook SSRF guard; append-only audit logs via PostgreSQL RLS; Redis AOF crash-recovery persistence; Linux/macOS deployment scripts (May 2026)
- **v1.97.0** — Encrypt Copilot LLM API keys at rest (Fernet/AES-128); GIN indexes on inventory JSONB columns; automatic history table archival with configurable retention (May 2026)
- **v1.96.0** — Operational Event Timeline: unified `operational_events` stream across 10 source tables, blast-radius correlation, Copilot context injection, tenant "Event History" portal screen with domain isolation (May 2026)
- **v1.95.0** — Advanced billing and metering system with prepaid accounts, regional pricing, multi-currency chargeback, and revenue leakage detection (May 2026)
- **v1.94.0** — Enterprise dashboards: Account Manager Portfolio (per-tenant SLA, vCPU, leakage alerts), Executive Health (fleet SLA gauge, MTTR), QBR PDF generation per customer (May 2026)

📋 **Full history → [CHANGELOG.md](CHANGELOG.md)**
