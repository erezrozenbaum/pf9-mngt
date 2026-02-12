# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-02-12

### Added
- **Landing Dashboard** with 14 real-time analytics endpoints and auto-refresh
  - Health summary, snapshot SLA compliance, capacity trends
  - Tenant risk scoring, host utilization, VM hotspots
  - Coverage risk, compliance drift, change compliance
  - Recent activity widget, capacity pressure analysis
- **17+ React UI components** with dark/light theme support
  - `LandingDashboard`, `HealthSummaryCard`, `SnapshotSLAWidget`
  - `TenantRiskScoreCard`, `TenantRiskHeatmapCard`, `HostUtilizationCard`
  - `CapacityTrendsCard`, `CapacityPressureCard`, `CoverageRiskCard`
  - `ComplianceDriftCard`, `ChangeComplianceCard`, `RecentActivityWidget`
  - `SnapshotMonitor`, `SnapshotPolicyManager`, `SnapshotAuditTrail`
  - `SnapshotComplianceReport`, `SystemLogsTab`, `APIMetricsTab`
  - `ThemeToggle`, `UserManagement`
- **Snapshot automation system** with policy-based scheduling
  - `snapshot_scheduler.py` — cron-style snapshot orchestration
  - `p9_auto_snapshots.py` — automated snapshot creation per policy
  - `p9_snapshot_policy_assign.py` — policy-to-volume assignment engine
  - `p9_snapshot_compliance_report.py` — SLA compliance reporting
  - `snapshot_policy_rules.json` — configurable policy definitions
- **Cross-tenant snapshot service user** (`snapshot_service_user.py`)
  - Dedicated service account for multi-tenant snapshot operations
  - Fernet-encrypted password storage support
  - Automatic role assignment per target project
  - Dual-session architecture (admin session + project-scoped session)
- **LDAP authentication** with RBAC (viewers, operators, admins, superadmins)
  - JWT access + refresh token authentication
  - Group-based role enforcement across all API endpoints
  - User management (create/delete/list) via LDAP admin operations
- **Database integration layer** (`db_writer.py`)
  - Automated inventory collection pipeline (PF9 API → PostgreSQL)
  - 22+ database tables with FK constraints and history tracking
- **Host metrics collector** (`host_metrics_collector.py`)
  - Collects hypervisor and VM metrics from PF9 hosts
  - Scheduled collection via Windows Task Scheduler
  - Shared metrics cache for monitoring service
- **Monitoring service** with Prometheus-compatible metrics endpoint
- **Interactive deployment wizard** (`deployment.ps1`)
  - Prompts for all customer-specific configuration
  - Auto-generates LDAP base DN from domain name
  - Fernet key generation for encrypted passwords
  - Auto-generates JWT secret keys
- **Comprehensive documentation**
  - `README.md` — Project overview, quick start, architecture
  - `DEPLOYMENT_GUIDE.md` — Step-by-step deployment instructions
  - `ADMIN_GUIDE.md` — Day-to-day administration reference
  - `ARCHITECTURE.md` — System design and component interaction
  - `SECURITY.md` — Security model, authentication, encryption
  - `SECURITY_CHECKLIST.md` — Pre-production security audit checklist
  - `SNAPSHOT_AUTOMATION.md` — Snapshot system design and configuration
  - `SNAPSHOT_SERVICE_USER.md` — Service user setup and troubleshooting
  - `API_REFERENCE.md` — Complete API endpoint documentation
  - `QUICK_REFERENCE.md` — Common commands and URLs cheat sheet
  - `KUBERNETES_MIGRATION_GUIDE.md` — Future K8s migration planning
  - `CONTRIBUTING.md` — Contribution guidelines
- **Docker Compose** orchestration for all services (API, UI, DB, LDAP, monitoring, snapshots)
- **Release automation** — `release.ps1` script and GitHub Action for version tagging

### Security
- Removed all customer-specific data from git-tracked files
  - No hardcoded domain names, passwords, IPs, or encryption keys in source
  - All sensitive values read from environment variables (`.env` file)
  - `.env` properly gitignored; `.env.example` provides template
- LDAP admin password passed via environment variable (not hardcoded)
- Snapshot service user password supports Fernet encryption at rest
- JWT secret auto-generated during deployment

[unreleased]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/erezrozenbaum/pf9-mngt/releases/tag/v1.0.0
