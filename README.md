# PF9 Management — Day-2 Operations Control Plane

> **Platform9 solves provisioning. pf9-mngt solves Day-2 operations at scale.**

*Operational complexity doesn't break at provisioning — it breaks during recovery, scaling, and tenant operations.*

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

## 🚀 Quick Facts

• **🏗️ 18-container microservices** — production-grade architecture  
• **📈 670+ commits, 270+ releases** — battle-tested codebase  
• **✅ 583 passing tests** — comprehensive test coverage  
• **🔒 Kubernetes-native** — Helm charts + ArgoCD GitOps  
• **🎮 Demo mode** — full product experience without Platform9  

[![Version](https://img.shields.io/badge/version-1.94.11-blue.svg)](CHANGELOG.md) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) [![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://www.docker.com/) [![Kubernetes](https://img.shields.io/badge/kubernetes-ready-green.svg)](https://kubernetes.io/)

*Used to model real-world MSP Day-2 operational scenarios.*

---

## 🔄 Three Core Workflows

### 1. 📸 Snapshot SLA Enforcement  
**Policy Definition** → **Automated Execution** → **Compliance Monitoring** → **Alert Generation** → **Audit Reports**

### 2. 🔄 VM Restore Under SLA Pressure  
**Select Target VM** → **Dry-Run Validation** → **Execute Restore** → **Real-time Monitoring** → **Compliance Audit**

### 3. 🗺️ Migration Planning & Execution  
**RVTools Import** → **Risk Assessment** → **Cohort Analysis** → **Wave Planning** → **PCD Deployment**

---

## 🎯 What This Replaces

| **Missing Platform9 Capability** | **Production Impact** | **pf9-mngt Solution** |
|-----------------------------------|----------------------|----------------------|
| **No RVTools equivalent** | Manual inventory exports, no drift detection | 29-resource-type inventory engine with historical tracking |
| **No native VM restore workflow** | Critical downtime during outages, manual reconstruction | Side-by-side and replace restore modes with automation |
| **No snapshot automation** | Manual backup processes, compliance gaps | Policy-based automation with SLA tracking |
| **No VMware migration planning** | Ad-hoc migration approach, business risk | End-to-end migration planner with risk assessment |
| **Limited tenant self-service** | High operational overhead, ticket volume | Isolated tenant portal with MFA and RBAC |
| **No comprehensive metering** | Revenue leakage, billing disputes | Multi-resource chargeback with efficiency scoring |

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

| Service | Stack | Purpose |
|---------|-------|---------|
| **Frontend UI** | React 19.2+ / TypeScript | 30+ management tabs + admin panel |
| **Backend API** | FastAPI / Python | 170+ REST endpoints, RBAC middleware |
| **Tenant Portal** | React + FastAPI | Isolated self-service interface |
| **Monitoring** | FastAPI / Python | Real-time metrics via Prometheus |
| **Database** | PostgreSQL 16 | 160+ tables, audit, metering, RLS |
| **+ 9 Workers** | Python | Snapshot, backup, metering, search, sync |

**Tech Stack:** React 19.2+ / TypeScript / FastAPI / PostgreSQL 16 / Redis / Docker / Kubernetes  
**Production Ready:** 583 tests, security scanning, observability, Kubernetes deployment  
*Built to solve real MSP operational gaps identified during live Platform9 evaluation.*

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

▶️ [**PF9 Management System — Full UI Walkthrough (15 min)**](https://www.youtube.com/watch?v=68-LQ9ugU_E)

---

## 📚 Documentation

| Document | Purpose |
|----------|---------|
| [Deployment Guide](docs/DEPLOYMENT_GUIDE.md) | Step-by-step setup instructions |
| [Admin Guide](docs/ADMIN_GUIDE.md) | Day-to-day administration |
| [Architecture](docs/ARCHITECTURE.md) | System design & data model |
| [Kubernetes Guide](docs/KUBERNETES_GUIDE.md) | Helm charts & production deployment |
| [Features Reference](docs/FEATURES_REFERENCE.md) | Complete technical deep-dive |

---

## ❓ FAQ

**Q: Does this replace the Platform9 UI?**  
No — it's a complementary engineering console for Day-2 operations.

**Q: Can I try without Platform9?**  
Yes — Demo Mode provides full functionality with sample data.

**Q: Is this production-ready?**  
Yes — 583 tests, Kubernetes deployment, security scanning, observability.

**Q: Minimum requirements?**  
Docker host: 4GB RAM, 2 CPU cores, network access to Platform9 endpoints.

---

## 🆕 Recent Highlights

- **v1.94.11** — Documentation alignment with enterprise features
- **v1.94.10** — Tenant portal chargeback fixes
- **v1.94.0** — Enterprise dashboard overhaul  
- **v1.93.0** — Kubernetes production ready
- **v1.92.0** — Role-based dashboards

📋 **Full history → [CHANGELOG.md](CHANGELOG.md)**