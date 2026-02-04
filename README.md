# Platform9 Management System

**Engineering Teams Add-On Platform: Enhanced Inventory, Monitoring & Daily Operations for Platform9**

An added-value management system designed for engineering teams to assist with daily tasks when managing Platform9 environments. This is **not** a replacement for the official Platform9 UI, but rather an engineering-focused complement that provides enhanced inventory visibility, operational tooling, and maintenance capabilities.

## 🎯 Overview

### What is Platform9?

Platform9 is a cloud infrastructure management platform that simplifies operating private and hybrid clouds. It brings together compute, storage, and networking management behind a unified, secure control plane and makes it easier for teams to manage virtualization and container environments.

### What runs under the hood

Platform9 environments are commonly backed by **OpenStack** services. That means this tool must translate OpenStack's distributed resources (Nova, Cinder, Neutron, Keystone) into a cohesive, operator-friendly view while keeping identity, tenancy, and RBAC boundaries intact.

### Why this project exists

This project does **not** replace the official Platform9 UI. It provides an engineering-focused, role-aware inventory and maintenance UI that complements Platform9 by improving day-to-day operational visibility. The goal is faster navigation, clearer context, and human-friendly naming (project/tenant/host names) instead of only UUID-based views.

It also delivers a wider view of the overall system and adds functionality such as snapshot management, volume management, and other operational tools that extend the current Platform9 UI. This creates an added-value engineering console to assist teams in managing Platform9 environments.

### Metadata and day‑to‑day operations challenges

OpenStack resources are highly dynamic and spread across multiple services. Capturing, storing, and presenting metadata at scale is challenging because:

- **Identifiers are fragmented**: Projects, domains, and resources use different IDs across services.
- **State changes are frequent**: VMs, volumes, and networks change status quickly and asynchronously.
- **Auditability matters**: Operators need a reliable history of changes and ownership.
- **Tasks are cross‑cutting**: Daily workflows (provision, attach, snapshot, resize, troubleshoot) touch multiple services.

This system focuses on day-to-day tasks by normalizing metadata into a single inventory view, then layering on role-aware actions and audit trails.

### Inventory + monitoring system logic

The enhanced inventory and monitoring experience is built on a few principles:

- **Unify resource models**: Normalize OpenStack objects into consistent entities (servers, volumes, networks, projects) with stable identifiers.
- **Join metadata with live metrics**: Merge configuration data with monitoring snapshots to show health and utilization in context.
- **Cache for speed, refresh for accuracy**: Use cached snapshots for fast UI rendering, then refresh incrementally for near real-time status.
- **Role-aware visibility**: Filter and display resources based on RBAC and tenant boundaries.
- **Operational signals first**: Highlight state, alerts, and recent changes so operators can act quickly.

### Key benefits

- **Unified operations**: Manage infrastructure, platform resources, and users from a single console.
- **Human-friendly visibility**: Project names, tenant names, host names instead of UUID-only views.
- **Built-in governance**: Role-based access control and audit history help enforce policies.
- **Operational speed**: Real-time monitoring and quick filtering reduce time-to-diagnosis.
- **Enhanced functionality**: Snapshot management, volume management, and other tools not available in standard Platform9 UI.
- **Lower complexity**: Consistent workflows reduce manual steps and errors.

## � Documentation

- **[LICENSE](LICENSE)** - MIT License

## �🚀 System Architecture

**Enterprise microservices-based platform** with 6 containerized services plus host-based automation:
- **Frontend UI** (React 19.2+/TypeScript/Vite) - Port 5173 - 14 management tabs + admin panel
- **Backend API** (FastAPI/Python) - Port 8000 - 40+ REST endpoints with RBAC middleware
- **LDAP Server** (OpenLDAP) - Port 389 - Enterprise authentication directory
- **Monitoring Service** (FastAPI/Python) - Port 8001 - Real-time metrics collection
- **Database** (PostgreSQL 16) - Port 5432 - 22+ tables with history tracking + auth audit
- **Database Admin** (pgAdmin4) - Port 8080
- **Host Scripts** (Python) - Scheduled automation via Windows Task Scheduler

## 🌟 Key Features

### Enterprise Authentication & Authorization
- **LDAP Integration**: Production-ready OpenLDAP authentication with configurable directory structure
- **Role-Based Access Control**: 4-tier permission system (Viewer, Operator, Admin, Superadmin)
- **JWT Token Management**: Secure 480-minute sessions with Bearer token authentication
- **RBAC Middleware**: Automatic permission enforcement on all resource endpoints
- **Audit Logging**: Complete authentication event tracking (login, logout, failed attempts, user management)
- **User Management**: LDAP user creation, role assignment, and permission management
- **Role-Based UI**: Dynamic tab visibility based on user permissions
- **System Audit**: 90-day retention with filtering by user, action, date range, and IP address

### Complete Infrastructure Management
- **19+ Resource Types**: Domains, Projects, VMs, Volumes, Snapshots, Networks, Subnets, Ports, Floating IPs, Routers, Security Groups & Rules, Hypervisors, Flavors, Images, Volume Types
- **Advanced User Management**: Multi-domain user collection (100+ users across 28 domains), role assignments, activity tracking, and comprehensive identity management
- **Multi-Tenant Support**: Full domain and project-level resource organization with complete user visibility across all tenants
- **Comprehensive Audit System**: Complete change tracking, deletion history, compliance reporting, and resource timeline analysis
- **RVTools Parity**: Excel/CSV exports with enhanced data masking and delta reporting
- **Real-time Synchronization**: Automated cleanup with historical preservation and change attribution

### Advanced Real-Time Monitoring
- **Host Metrics**: Live CPU, memory, storage from PF9 compute nodes via Prometheus node_exporter (port 9388)
- **VM Metrics**: Individual VM resource tracking via libvirt_exporter (port 9177) *[Currently requires PF9 engineering support]*
- **Automated Collection**: Background collection every 30 minutes via Windows Task Scheduler
- **Cache-Based Storage**: Persistent metrics survive service restarts
- **Integrated Dashboard**: Real-time monitoring tab with auto-refresh in management UI

### Enterprise-Grade Snapshot Management
- **Metadata-Driven Policies**: Volume-level configuration via OpenStack metadata
- **Multi-Policy Support**: daily_5, monthly_1st, monthly_15th with independent retention
- **SLA Compliance**: Configurable thresholds with detailed reporting
- **Policy Assignment Rules**: JSON-driven automatic policy assignment based on volume properties
- **Comprehensive Reporting**: Detailed compliance reports with tenant/domain aggregation

### Modern Web Management Interface
- **React 19.2+ Dashboard**: 14 comprehensive management tabs (Servers, Volumes, Snapshots, Networks, Subnets, Ports, Floating IPs, Domains, Projects, Flavors, Images, Hypervisors, Users, Admin, History, Audit, Monitoring)
- **Role-Based UI**: Admin tab visible only to admin/superadmin roles
- **Secure Login**: LDAP authentication with JWT token management
- **Real-Time Data**: Auto-refresh capabilities with efficient pagination across all endpoints
- **Advanced Filtering**: Multi-field filtering, sorting, and search across all 19+ resource types
- **Administrative Operations**: Create/delete flavors and networks, user management, role assignments (admin+ only)
- **Historical Analysis**: Resource timeline tracking, change velocity metrics, compliance dashboards
- **Theme Support**: Light/dark mode toggle with persistent preferences and responsive design

### Enterprise Automation & Integration
- **Single-Command Deployment**: Complete stack setup via `startup.ps1` with LDAP initialization
- **Hybrid Architecture**: Scripts work standalone or with full web services
- **Database Flexibility**: Excel/CSV generation works with or without PostgreSQL
- **Windows Integration**: Full Task Scheduler automation support
- **Docker Native**: Complete containerized deployment with docker-compose

## 🚀 Quick Start

### Prerequisites
- **Python 3.11+** with packages: `requests`, `openpyxl`, `psycopg2-binary`, `aiohttp`, `aiofiles`
- **Docker & Docker Compose** (for complete platform)
- **Valid Platform9 credentials** (service account recommended)
- **Network access** to Platform9 cluster and compute nodes (for monitoring)
- **Windows environment** (for automated scheduling via Task Scheduler)

### 1. Complete Automated Setup (Recommended)
```powershell
# Clone and navigate to repository
git clone <repository-url>
cd pf9-mngt

# Configure environment (CRITICAL: No quotes around values)
cp .env.template .env
# Edit .env with your Platform9 credentials

# One-command complete setup
.\startup.ps1

# Access services:
# - UI: http://localhost:5173
# - API: http://localhost:8000
# - API Docs: http://localhost:8000/docs
# - Monitoring: http://localhost:8001
# - Database Admin: http://localhost:8080
```

### 2. Environment Configuration
Create `.env` file with your credentials (**CRITICAL: No quotes around values**):
```bash
# Platform9 Authentication
PF9_USERNAME=your-service-account@company.com
PF9_PASSWORD=your-secure-password
PF9_AUTH_URL=https://your-cluster.platform9.com/keystone/v3
PF9_USER_DOMAIN=Default
PF9_PROJECT_NAME=service
PF9_PROJECT_DOMAIN=Default
PF9_REGION_NAME=region-one

# Database Configuration (for Docker services)
POSTGRES_USER=pf9
POSTGRES_PASSWORD=generate-secure-password-here
POSTGRES_DB=pf9_mgmt
```

### 3. Manual Docker Setup
```bash
# Start all services
docker-compose up -d

# Check service status
docker-compose ps

# View service logs
docker-compose logs pf9_api
docker-compose logs pf9_ui
```

### 4. Standalone Script Usage
```bash
# Install Python dependencies
pip install requests openpyxl psycopg2-binary

# Run RVTools export (standalone)
python pf9_rvtools.py

# Generate compliance report
python snapshots/p9_snapshot_compliance_report.py

# Assign snapshot policies
python snapshots/p9_snapshot_policy_assign.py

# Run automated snapshots
python snapshots/p9_auto_snapshots.py
```

## 📊 Core Components

### 1. Infrastructure Discovery (`pf9_rvtools.py`)
Comprehensive OpenStack inventory with RVTools-compatible exports:
- **19+ Resource Types**: Complete infrastructure coverage including user management
- **Excel/CSV Export**: Customer-data-safe with masking options
- **Database Integration**: Optional PostgreSQL storage for historical tracking
- **Delta Reporting**: Change detection and trend analysis

### 2. User Management System
**Multi-Domain User Collection**:
- **Cross-domain visibility**: Collects users from all 28 OpenStack domains (20 with active users)
- **Role assignment tracking**: Monitors 100+ role assignments across the infrastructure
- **Activity monitoring**: Tracks user last seen timestamps and account status
- **Role inference system**: Intelligent role assignment when API access is limited
- **Domain-scoped authentication**: Ensures complete user enumeration across tenants

**User Data Collected**:
- User identity and contact information
- Domain associations and project memberships  
- Role assignments (admin, member, service roles)
- Account status (enabled/disabled)
- Activity timestamps (last seen, creation dates when available)
- User descriptions and metadata

### 3. Snapshot Management
**Automated Creation** (`snapshots/p9_auto_snapshots.py`):
- Policy-driven volume snapshots
- Multi-policy support per volume
- SLA compliance enforcement
- Retention management

**Policy Assignment** (`snapshots/p9_snapshot_policy_assign.py`):
- JSON-driven rule engine
- Volume property matching
- Bulk policy assignment

**Compliance Reporting** (`snapshots/p9_snapshot_compliance_report.py`):
- Detailed SLA analysis
- Tenant/Domain aggregation
- Policy adherence tracking

### 3. Real-Time Monitoring
**Host Metrics** (`host_metrics_collector.py`):
- Prometheus node_exporter integration (port 9388)
- Windows Task Scheduler automation
- Persistent cache storage
- CPU, Memory, Storage tracking

**Monitoring Service** ([monitoring/main.py](monitoring/main.py)):
- FastAPI-based metrics API
- Cache-based data delivery
- Auto-refresh endpoints
- Integration with main UI

### 4. Web Management Platform
**Backend API** ([api/main.py](api/main.py)):
- 20+ REST endpoints
- PostgreSQL integration
- Administrative operations
- OpenAPI documentation

**Frontend UI** ([pf9-ui/src/App.tsx](pf9-ui/src/App.tsx)):
- React 19.2 with TypeScript
- Vite build system
- Real-time data refresh
- Advanced filtering and pagination

## 🛠️ Administration

### Database Management
```bash
# Connect to database
psql -h localhost -U pf9 -d pf9_mgmt

# Backup database
docker exec pf9_db pg_dump -U pf9 pf9_mgmt > backup.sql

# Restore database
docker exec -i pf9_db psql -U pf9 pf9_mgmt < backup.sql
```

### Service Management
```bash
# Restart specific service
docker-compose restart pf9_api

# Scale services
docker-compose up -d --scale pf9_api=2

# View resource usage
docker stats
```

### Monitoring Setup
1. **Automatic**: Run `startup.ps1` (sets up Task Scheduler)
2. **Manual**: 
   ```powershell
   # Create scheduled task for metrics collection
   schtasks /create /tn "PF9 Metrics" /tr "python C:\pf9-mngt\host_metrics_collector.py" /sc minute /mo 30
   ```

## 🔧 Configuration Files

- **[docker-compose.yml](docker-compose.yml)**: Service orchestration
- **[.env.template](.env.template)**: Environment configuration template
- **[db/init.sql](db/init.sql)**: Database schema with 19+ tables
- **[snapshot_policy_rules.json](snapshots/snapshot_policy_rules.json)**: Automatic policy assignment rules
- **[startup.ps1](startup.ps1)**: Complete automation script

## 📚 Documentation

- **[DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md)**: Step-by-step deployment instructions
- **[ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md)**: Comprehensive administration guide
- **[QUICK_REFERENCE.md](docs/QUICK_REFERENCE.md)**: Quick commands and examples
- **[SECURITY_CHECKLIST.md](docs/SECURITY_CHECKLIST.md)**: Security assessment and hardening

## 🆘 Troubleshooting

### Common Issues
1. **"Failed to fetch" in UI**:
   - Check API service: `docker-compose logs pf9_api`
   - Verify .env credentials
   - Test connection: `curl http://localhost:8000/health`

2. **Empty monitoring data**:
   - Run metrics collection: `python host_metrics_collector.py`
   - Check task scheduler: `schtasks /query /tn "PF9 Metrics"`
   - Verify node_exporter on PF9 hosts (port 9388)

3. **Database connection errors**:
   - Verify PostgreSQL: `docker-compose logs db`
   - Check credentials in .env
   - Reset database: `docker-compose down -v && docker-compose up -d`

### Support Resources
- **Logs**: `docker-compose logs <service-name>`
- **Health checks**: `curl http://localhost:8000/health`
- **API documentation**: `http://localhost:8000/docs`
- **Database admin**: `http://localhost:8080` (admin@pf9-mgmt.com / admin123)
# Run inventory collection (standalone)
python pf9_rvtools.py

# Check generated reports
dir "C:\Reports\Platform9\*.xlsx"  # Windows
ls ~/Reports/Platform9/*.xlsx       # Linux/Mac
```

## 🖥️ Usage Modes

### Standalone Scripts (No Docker Required)
Scripts automatically load `.env` file and work independently:

```bash
# Data collection and RVTools export
python pf9_rvtools.py

# Automated snapshot management  
python snapshots/p9_auto_snapshots.py --policy daily_5 --dry-run
python snapshots/p9_auto_snapshots.py --policy daily_5

# Compliance reporting
python snapshots/p9_snapshot_compliance_report.py --input latest_export.xlsx --output compliance.xlsx

# Policy assignment
python snapshots/p9_snapshot_policy_assign.py --config snapshots/snapshot_policy_rules.json --dry-run
```

### Full Stack with Web UI (Docker Required)
```bash
# Start all services (database, API, web UI)
docker-compose up -d

# IMPORTANT: After manual docker-compose up, run this to enable monitoring:
.\fix_monitoring.ps1

# Access web interface
# http://localhost:5173 - Management UI (with Monitoring tab)
# http://localhost:8000/docs - API Documentation  
# http://localhost:8080 - Database Admin (pgAdmin)
```

## 📊 Features

### Core Capabilities
- **Real-time Inventory**: VMs, volumes, snapshots, networks, hypervisors, flavors
- **Volume Metadata Management**: Auto-snapshot policies and retention settings with visual indicators
- **Automated Snapshots**: Policy-driven with configurable retention periods
- **Compliance Reporting**: Detailed policy adherence tracking and SLA monitoring
- **RVTools-Compatible Exports**: XLSX/CSV with delta tracking and data masking
- **Multi-tenant Support**: Domain and project-level filtering and management
- **Administrative Functions**: Create/delete flavors and networks via API/UI

### Volume Management Features
- **Snapshot Policy Visualization**: Color-coded badges showing auto-snapshot status (Enabled/Disabled)
- **Policy Details Display**: View snapshot policies (daily_5, monthly_15th, etc.) directly in volume list
- **Metadata Inspection**: Complete volume metadata viewer with raw JSON display
- **Retention Settings**: Detailed retention policy configuration per volume
- **Volume Type Support**: Full volume type identification and filtering

### Automation Features  
- **Scheduled Data Collection**: Windows Task Scheduler / Linux cron compatible
- **Multiple Snapshot Policies**: daily, weekly, monthly with flexible retention
- **Volume Metadata-Driven**: Policies applied via OpenStack volume metadata
- **Compliance Tracking**: SLA monitoring and policy violation reporting

### Security Features
- **Environment-based Configuration**: No hardcoded credentials
- **Git-safe Setup**: Credentials never committed to repository  
- **Optional Database**: Scripts work with or without database services
- **Customer Data Masking**: Privacy-compliant exports for third parties

## 🔧 Configuration

### Complete Automation with startup.ps1
For zero-intervention deployment (recommended):
```powershell
# One-command setup - starts everything needed
.\startup.ps1

# This automatically:
# - Stops existing services for clean startup
# - Collects initial metrics from PF9 hosts  
# - Sets up scheduled metrics collection task (every 30 minutes)
# - Starts all Docker services (DB, API, UI, Monitoring)
# - Verifies all services are operational
# - Creates "PF9 Metrics Collection" Windows scheduled task

# To stop everything
.\startup.ps1 -StopOnly
```

**⚠️ Important**: startup.ps1 only sets up **metrics collection**. For complete automation, also create the **RVTools inventory collection** scheduled task manually (see below).

### Environment Configuration (Update .env)
```bash
# Platform9 Authentication
PF9_USERNAME=your-service-account@company.com
PF9_PASSWORD=your-secure-password
PF9_AUTH_URL=https://your-cluster.platform9.com/keystone/v3
PF9_USER_DOMAIN=Default
PF9_PROJECT_NAME=service
PF9_PROJECT_DOMAIN=Default
PF9_REGION_NAME=region-one

# Database Configuration (for Docker)
POSTGRES_USER=pf9
POSTGRES_PASSWORD=change-this-secure-password
POSTGRES_DB=pf9_mgmt

# Monitoring Configuration (NEW)
PF9_HOSTS=172.17.95.2,172.17.95.3,172.17.95.4,172.17.95.5
METRICS_CACHE_TTL=60
```

### Windows Task Scheduler Setup
For complete automation, set up scheduled tasks for both metrics and inventory collection:

#### 1. **PF9 Metrics Collection** (Automated by startup.ps1)
- **Task Name**: "PF9 Metrics Collection" 
- **Schedule**: Every 30 minutes
- **Action**: `python host_metrics_collector.py --once`
- **Auto-created by**: `.\startup.ps1` command

#### 2. **RVTools Inventory Collection** (Manual Setup Required)
Create additional scheduled task for inventory data collection:
```
Action: Start a program
Program/script: C:\Python313\python.exe
Add arguments: C:\pf9-mngt\pf9_rvtools.py  
Start in: C:\pf9-mngt
Schedule: Daily at 2:00 AM (recommended)
```

**Manual Task Creation**:
```powershell
# Create RVTools daily collection task
schtasks /create /tn "PF9 RVTools Collection" /tr "python C:\pf9-mngt\pf9_rvtools.py" /sc daily /st 02:00 /sd 01/01/2026
```

### Snapshot Policies
Configure volume metadata for automated snapshots:
```bash
# Daily snapshots with 5-day retention
openstack volume set --property auto_snapshot=true \
                    --property snapshot_policies=daily_5 \
                    --property retention_daily_5=5 \
                    <volume-id>

# Multiple policies
openstack volume set --property auto_snapshot=true \
                    --property snapshot_policies=daily_5,monthly_1st \
                    --property retention_daily_5=5 \
                    --property retention_monthly_1st=12 \
                    <volume-id>
```

## 🖥️ Web Interface Features

### Volume Management Dashboard
The web interface provides comprehensive volume metadata visualization:

- **📊 Enhanced Volume Table**: 
  - Auto Snapshot status with color-coded badges (🟢 Enabled / ⚪ Disabled)
  - Snapshot Policy display showing active policies (e.g., daily_5,monthly_15th)
  - Volume Type identification (infinidat-pool2, etc.)
  - Server attachment details

- **📋 Volume Details Panel**:
  - Complete metadata inspection with expandable JSON viewer
  - Snapshot policy configuration display
  - Retention settings breakdown
  - Server and device attachment information

- **🎨 Visual Indicators**:
  - Green badges for enabled auto-snapshot volumes
  - Gray badges for volumes without auto-snapshot
  - Clear policy names (daily_5, monthly_15th, monthly_1st)

### Navigation
- Access via: `http://localhost:5173`
- Switch to **Volumes** tab to view enhanced metadata features
- Click any volume row to see detailed metadata in the right panel

## 📁 Project Structure
```
pf9-mngt/
├── docs/                    # Documentation
│   ├── ADMIN_GUIDE.md      # Comprehensive administration guide
│   ├── QUICK_REFERENCE.md  # Command quick reference
│   └── SECURITY_CHECKLIST.md # Security considerations
├── api/                     # FastAPI backend
├── pf9-ui/                 # React frontend  
├── monitoring/             # Real-time monitoring service
│   ├── main.py            # FastAPI monitoring API
│   ├── models.py          # Pydantic data models
│   ├── prometheus_client.py # Prometheus integration
│   └── Dockerfile         # Container configuration
├── db/                     # Database initialization
├── .env.template           # Environment configuration template
├── startup.ps1             # Complete automation script (NEW)
├── host_metrics_collector.py # Real-time metrics collection (NEW)
├── cleanup_snapshots.py    # Database cleanup utilities (NEW)  
├── metrics_cache.json     # Persistent metrics storage (NEW)
├── pf9_rvtools.py          # Main inventory collection script
├── snapshots/              # Snapshot tooling
│   ├── p9_auto_snapshots.py            # Snapshot automation
│   ├── p9_snapshot_compliance_report.py # Compliance reporting
│   ├── p9_snapshot_policy_assign.py     # Policy management
│   └── snapshot_policy_rules.json       # Policy assignment rules
├── p9_common.py            # Shared utilities
└── docker-compose.yml      # Container orchestration with monitoring
```

## 🚨 Important Notes

### Environment File Format
**CRITICAL**: Do not use quotes around values in `.env` file:
```bash
# ✅ CORRECT
PF9_USERNAME=user@company.com

# ❌ WRONG  
PF9_USERNAME="user@company.com"
```

### Database Dependency
- Scripts work **with or without** database services running
- Database stores historical data and enables web UI
- Excel/CSV exports generated regardless of database availability

### First-Time Setup Security
1. **NEVER commit `.env` file** to version control
2. **Rotate credentials** if accidentally exposed  
3. **Use service accounts** not personal credentials
4. **Test with `--dry-run`** before production use

## 📖 Documentation
- **[System Overview](docs/SYSTEM_OVERVIEW.md)** - Complete feature matrix and current capabilities
- **[Architecture Guide](docs/ARCHITECTURE.md)** - Technical architecture and component details- **[Administrator Guide](docs/ADMIN_GUIDE.md)** - Comprehensive setup and management
- **[Quick Reference](docs/QUICK_REFERENCE.md)** - Common commands and troubleshooting  
- **[Security Checklist](docs/SECURITY_CHECKLIST.md)** - Security considerations and hardening

## 🐛 Troubleshooting

### Common Issues

**Script fails with authentication error**:
- Verify `.env` file exists and has correct credentials
- Check Platform9 cluster URL and service account permissions
- Test credentials: `curl -k https://your-cluster.com/keystone/v3`

**Database connection failed**:
- Normal when running scripts standalone
- Start Docker services if database functionality needed: `docker-compose up -d`

**Environment variables not loading**:  
- Ensure `.env` file is in same directory as script
- Check file format (no quotes around values)
- Verify file encoding is UTF-8

**Monitoring service not working**:
- Check if monitoring service is running: `docker ps | grep pf9_monitoring`
- Verify PF9 hosts are accessible: `curl http://172.17.95.2:9388/metrics`
- Check scheduled task: `schtasks /query /tn "PF9 Metrics Collection"`
- Manual metrics collection: `python host_metrics_collector.py --once`

**Data synchronization issues**:  
- Run cleanup script: `python cleanup_snapshots.py`
- Force data sync: `python pf9_rvtools.py`
- Check database record counts via pgAdmin or CLI

## 📄 License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file for details.

**Copyright © 2026 Erez Rozenbaum and Contributors**

## 👤 About the Creator

**Erez Rozenbaum** - Original Developer & Maintainer

This project was developed as a comprehensive solution for Platform9/OpenStack infrastructure management and real-time monitoring, bringing enterprise-grade automation and visibility to OpenStack environments.

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on:
- How to report bugs
- How to suggest features
- How to submit code changes
- Development setup
- Coding standards

## 💝 Support the Project

If you find this project useful, please consider:
- ⭐ Starring the repository
- 🐛 Reporting bugs and issues
- 💻 Contributing code improvements
- 📝 Improving documentation
- 💬 Sharing feedback and suggestions

## 📚 Resources

- [Quick Reference Guide](docs/QUICK_REFERENCE.md)
- [Admin Guide](docs/ADMIN_GUIDE.md)
- [Architecture Overview](docs/ARCHITECTURE.md)
- [Security Guide](docs/SECURITY.md)
- [Development Notes](docs/DEVELOPMENT_NOTES.md)
- [Contributing Guidelines](CONTRIBUTING.md)

---

**Project Status**: Active Development  
**Last Updated**: February 4, 2026  
**Version**: 1.0