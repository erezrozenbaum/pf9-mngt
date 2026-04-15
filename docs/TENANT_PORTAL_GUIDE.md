# Tenant Self-Service Portal — Operator Guide

**Version**: 1.84.9  
**Last Updated**: April 15, 2026  
**Audience**: Platform administrators enabling and managing the tenant self-service portal

---

## Overview

The tenant self-service portal is a completely isolated web application that lets your Platform9 end-customers (tenants) view and manage their own infrastructure without exposing the admin panel.

**What tenants can do:**
- View their own VMs, volumes, and snapshots
- Monitor availability and resource metrics scoped to their projects
- Initiate side-by-side VM restores (non-destructive — always creates a new VM)
- View operational runbooks that you have explicitly published to them
- See their own restore job history and audit activity

**What tenants cannot do:**
- See other tenants' data (enforced at the PostgreSQL RLS layer, not just application code)
- Access admin management endpoints
- Execute destructive operations not permitted by the access policy you configure
- Modify infrastructure directly — this is a read + controlled-restore portal

**What admins control:**
- Which Keystone users may log in (allowed list per control plane)
- Which OpenStack projects are visible to each user
- MFA policy (TOTP required, email OTP, or none)
- Per-customer branding (logo, accent colour, portal title, favicon)
- Session revocation, audit review, MFA reset

---

## Architecture

```
                  ┌─────────────────────────────┐
                  │   nginx-ingress-tenant        │  (Kubernetes: dedicated
                  │   (or nginx in Docker)        │   MetalLB IP, separate
                  └────────────┬────────────────┘   from admin ingress)
                               │
              ┌────────────────▼────────────────┐
              │   tenant_portal (FastAPI, :8010)  │
              │   • JWT role=tenant               │
              │   • Redis session binding         │
              │   • IP-change detection           │
              │   • Per-user rate limiting        │
              └────────┬──────────────┬──────────┘
                       │              │
          ┌────────────▼──┐  ┌────────▼────────┐
          │ PostgreSQL     │  │ Redis            │
          │ (RLS enforced) │  │ (sessions, OTP,  │
          │ tenant_portal  │  │  branding cache) │
          │ _role          │  └─────────────────┘
          └───────────────┘

              ┌───────────────────────────────┐
              │   tenant-ui (React SPA)        │
              │   nginx :8083 (prod)           │
              │   Vite   :8082 (dev override)  │
              └───────────────────────────────┘
```

The tenant portal API (`tenant_portal/`) is a **completely separate FastAPI process** from the main admin API (`api/`). It uses its own JWT signing key, its own Redis key namespace, and connects to PostgreSQL using the `tenant_portal_role` database role — which has only `SELECT` permission on five inventory tables, each protected by Row-Level Security policies that restrict rows to the tenant's own projects.

The main admin API (`api/`) continues to manage admin operations and hosts the tenant portal admin endpoints under `/api/admin/tenant-portal/`.

---

## Prerequisites

Before enabling the portal for a customer:

| Requirement | Where to check |
|-------------|---------------|
| `TENANT_JWT_SECRET` env var set | `docker compose config pf9_tenant_portal` |
| `TENANT_DB_PASSWORD` configured | Secrets — `secrets/tenant_db_password` |
| SMTP configured (for email OTP) | Admin → System → SMTP Settings |
| Customer has a Keystone user in your PF9 | PF9 Keystone or `GET /api/users` |
| Tenant portal service is running | `docker compose ps pf9_tenant_portal` |
| Tenant UI service is running | `docker compose ps pf9_tenant_ui` |

---

## Enabling the Tenant Portal for a Customer

### Step 1 — Identify the customer's Keystone user ID

```bash
# Via the pf9-mngt admin API
GET /api/users?domain=<customer_domain>

# Response includes keystone_user_id for each user
```

### Step 2 — Grant portal access via the Admin UI

Navigate to **Admin → 🏢 Tenant Portal → Access Management** and click **Grant Access**. Provide:
- The customer's Keystone user ID
- The control plane ID (default: `default`)
- The list of OpenStack project IDs the customer may see
- (Optional) An access expiry date

### Step 3 — Grant access via API (alternative)

```bash
curl -X PUT https://<admin-host>/api/admin/tenant-portal/access/<cp_id> \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "keystone_user_id": "<uid>",
    "enabled": true,
    "allowed_project_ids": ["<project_id_1>", "<project_id_2>"],
    "mfa_required": true
  }'
```

### Step 4 — Configure branding (optional but recommended)

```bash
curl -X PUT https://<admin-host>/api/admin/tenant-portal/branding/<cp_id> \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "logo_url": "https://cdn.customer.com/logo.png",
    "accent_color": "#2563eb",
    "portal_title": "Customer Infrastructure Portal",
    "favicon_url": "https://cdn.customer.com/favicon.ico"
  }'
```

Branding is fetched by the tenant-ui on load from `GET /tenant/branding` (unauthenticated, 60 s cache). If no branding row exists, safe defaults are returned (`accent_color: #3b82f6`, `portal_title: "Customer Portal"`).

### Step 5 — Send the portal URL to the customer

| Deployment | URL |
|------------|-----|
| Docker Compose (dev) | `http://localhost:8083/` |
| Docker Compose (dev Vite) | `http://localhost:8082/` |
| Kubernetes | `https://<tenant-portal-domain>/` (your `nginx-ingress-tenant` hostname) |

The customer authenticates with their **Platform9 Keystone credentials** (email + password). MFA is enforced at login if `mfa_required: true` was set in the access config.

---

## Access Management Reference

### View access configuration

```bash
GET /api/admin/tenant-portal/access/<cp_id>
# Returns: all access rows for the CP, including allowed_project_ids, mfa_required, enabled, expiry
```

### View all users for a control plane

```bash
GET /api/admin/tenant-portal/users/<cp_id>
# Returns: user list with access status, last_seen, session count
```

### Revoke access

```bash
curl -X PUT https://<admin-host>/api/admin/tenant-portal/access/<cp_id> \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"keystone_user_id": "<uid>", "enabled": false}'
```

---

## Session Management

### View active sessions

```bash
GET /api/admin/tenant-portal/sessions/<cp_id>
# Returns: session list — user, IP, created_at, last_seen, session_id
```

### Revoke all sessions for a control plane

```bash
DELETE /api/admin/tenant-portal/sessions/<cp_id> \
  -H "Authorization: Bearer <admin_token>"
# Use this when rotating credentials, after a security incident, or to force re-auth
```

Sessions are automatically invalidated when:
- The user's IP address changes mid-session (IP binding, configurable)
- Access is revoked via the admin API
- The JWT TTL expires (configurable, default 480 minutes)
- Admin explicitly calls the DELETE sessions endpoint

---

## Branding Configuration

| Field | Type | Notes |
|-------|------|-------|
| `logo_url` | URL string | HTTPS recommended; displayed top-left in tenant-ui |
| `accent_color` | `#rrggbb` or `#rgb` | Must be a valid hex colour; used for primary buttons and highlights |
| `portal_title` | string | Shown in browser title bar and login screen |
| `favicon_url` | URL string or null | Optional; falls back to pf9-mngt default favicon |

The branding endpoint (`GET /tenant/branding`) is **unauthenticated** — it must be accessible before login so the login page can display customer branding. The 60-second Redis cache prevents DB pressure during high traffic.

The admin UI's **Branding** sub-tab provides a form with a live colour picker and preview.

---

## MFA Configuration

Two MFA methods are supported:

### TOTP (Google Authenticator / Authy)
- User scans a QR code during first login
- Receives 8 one-time backup codes (bcrypt-hashed in DB)
- Subsequent logins require valid TOTP code after password authentication

### Email OTP
- OTP sent to user's Keystone-registered email address
- SHA-256 hashed in Redis, 10-minute TTL
- Rate-limited: maximum 5 attempts before lockout

### Resetting MFA for a user

If a customer loses their authenticator app:

```bash
DELETE /api/admin/tenant-portal/mfa/<cp_id>/<keystone_user_id> \
  -H "Authorization: Bearer <admin_token>"
# Returns: {"cleared": true}
# The user will be prompted to re-enrol TOTP on next login
```

This action is also available in the Admin UI → Tenant Portal → **Branding** sub-tab. It creates a full audit log entry.

---

## Audit Log

Every tenant API call writes an immutable entry to `tenant_action_log` — atomically with the data query.

```bash
GET /api/admin/tenant-portal/audit/<cp_id>?limit=100&offset=0&user_id=<uid>&action=<action>&from=2026-04-01&to=2026-04-15
```

Captured fields per entry:
- `user_id` (Keystone user ID)
- `action` (e.g. `list_vms`, `restore_execute`, `view_snapshot`)
- `resource_id` (if applicable)
- `ip_address`
- `timestamp`
- `response_status`

The audit log is available in the Admin UI → Tenant Portal → **Audit Log** sub-tab with user, action, and date range filters.

---

## What Tenants See — The 7 Screens

| Screen | Description |
|--------|-------------|
| **Dashboard** | Overview cards: VM count, running VMs, storage usage, snapshot compliance %, active restore jobs |
| **Infrastructure** | VM list with status, spec, volumes; volume list with attachment status |
| **Snapshot Coverage** | 30-day calendar showing which VMs had snapshots each day; compliance % per VM |
| **Monitoring** | Per-VM metrics (CPU, RAM), 7-day and 30-day availability % |
| **Restore Center** | 3-step wizard: select snapshot → review plan → confirm restore. Job list with live progress. All restores are side-by-side (non-destructive: creates a new VM alongside the original). |
| **Runbooks** | Read-only catalogue of runbooks you have published to the tenant (filtered by `runbook_project_tags`) |
| **Activity Log** | Filterable table of the tenant's own actions in the portal — with timestamps, resource references, and response status |

---

## Making Runbooks Visible to Tenants

Runbooks are opt-in per tenant. To make a runbook visible to a specific tenant's projects:

1. Set `is_tenant_visible = true` on the runbook row:
   ```sql
   UPDATE runbooks SET is_tenant_visible = true WHERE name = '<runbook_name>';
   ```

2. Tag the runbook to the tenant's project(s):
   ```sql
   INSERT INTO runbook_project_tags (runbook_name, project_id)
   VALUES ('<runbook_name>', '<customer_project_id>');
   ```

Tenants see only runbooks tagged to their allowed project IDs. Results are read-only — tenants cannot trigger runbooks from the portal (tenant-triggered execution is a planned v2 feature).

---

## Kubernetes Deployment

The tenant portal uses a **dedicated nginx ingress controller** (`nginx-ingress-tenant`) on its own MetalLB IP pool — completely separate from the admin panel's `nginx-ingress-admin`.

This means:
- Tenant and admin TLS certificates are isolated
- You can apply different WAF/ModSecurity rules per ingress
- Tenant-portal rate limiting is independent of admin portal limits
- A traffic spike on the tenant portal does not affect admin ingress

### Key Helm values

```yaml
# k8s/helm/pf9-mngt/values.yaml
tenantPortal:
  enabled: true
  replicaCount: 2
  image:
    repository: ghcr.io/erezrozenbaum/pf9-mngt/tenant_portal
    tag: latest

tenantUi:
  enabled: true
  replicaCount: 1
  image:
    repository: ghcr.io/erezrozenbaum/pf9-mngt/tenant_ui
    tag: latest
  ingress:
    ingressClassName: nginx-tenant   # uses the dedicated ingress controller
    host: portal.your-domain.com
```

### Namespace and NetworkPolicy

The tenant portal pod is blocked by `NetworkPolicy` from reaching the admin API, LDAP, and SMTP. It may only egress to PostgreSQL (port 5432) and Redis (port 6379).

### Separate TLS certificate

Configure your TLS secret for the tenant portal hostname separately from the admin panel:

```bash
kubectl create secret tls tenant-portal-tls \
  --cert=path/to/portal.crt \
  --key=path/to/portal.key \
  -n pf9-mngt
```

---

## Health Checks and Monitoring

| Check | Command |
|-------|---------|
| Tenant portal API health | `curl http://localhost:8010/tenant/health` |
| Tenant portal API logs | `docker compose logs pf9_tenant_portal --tail=50` |
| Tenant UI health | `curl http://localhost:8083/` (prod) |
| Tenant UI logs | `docker compose logs pf9_tenant_ui --tail=50` |
| Active session count | `GET /api/admin/tenant-portal/sessions/<cp_id>` |
| Kubernetes pod status | `kubectl get pods -n pf9-mngt -l app=tenant-portal` |

---

## Troubleshooting

### Customer cannot log in

1. Check that access is granted: `GET /api/admin/tenant-portal/users/<cp_id>` — verify `enabled: true`
2. Check Keystone credentials: the tenant portal uses Keystone passthrough — if their PF9 password changed, they will get a 401 at login
3. Check SMTP if email OTP is enabled: `docker compose logs pf9_api | grep -i smtp`
4. Check rate limiting: too many failed MFA attempts lock the account; check `tenant_portal_mfa.failed_attempts` in PostgreSQL

### Tenant sees empty screens

1. Verify the allowed project IDs in the access config match the customer's actual OpenStack projects
2. Check that the inventory sync has run: `GET /api/system/last-sync`
3. Check the RLS configuration: `docker compose exec pf9_db psql -U pf9 -d pf9_mgmt -c "SELECT session_user, current_user;"`

### Branding not showing

1. Check that a branding row exists: `GET /api/admin/tenant-portal/branding/<cp_id>`
2. Clear the Redis branding cache: `docker compose exec pf9_redis redis-cli DEL tenant_branding:<cp_id>`
3. Verify the logo URL is publicly accessible (HTTPS, no auth required — the browser fetches it directly)

### Session keeps expiring unexpectedly

Check for IP address changes — if the customer is behind a NAT that rotates source IPs, sessions will be invalidated by the IP-binding check. You can increase the IP-binding window in the tenant portal config or disable it for that control plane.

---

## Security Reference

| Control | Implementation |
|---------|---------------|
| Data isolation | PostgreSQL Row-Level Security on 5 tables using `tenant_portal_role` — data is filtered at the DB layer |
| JWT isolation | Separate signing key from admin JWT; `role=tenant` claim — admin tokens are explicitly rejected at every endpoint |
| Session binding | Session token stored in Redis; validated against stored IP on every request |
| MFA | TOTP (RFC 6238) with 8 bcrypt-hashed backup codes, or email OTP (SHA-256 hash, 10 min TTL) |
| Rate limiting | Per Keystone user ID: 60 req/min for data endpoints, 5 req/min for auth endpoints |
| Network isolation | Kubernetes NetworkPolicy blocks tenant portal from reaching admin API (port 8000), LDAP (port 389/636), SMTP (port 465/587) |
| Audit | Every API call writes an immutable `tenant_action_log` row atomically with the data query |
| Input validation | All request bodies validated with Pydantic v2; `accent_color` validated as hex regex |
| CORS | Tenant portal only accepts requests from the `tenant-ui` origin (configurable `TENANT_CORS_ORIGINS`) |

---

## Related Documentation

| Document | Link |
|----------|------|
| API Reference — Tenant Portal section | [API_REFERENCE.md](API_REFERENCE.md#tenant-portal-api--port-8010-v1840) |
| Admin Guide — Section 12 | [ADMIN_GUIDE.md](ADMIN_GUIDE.md#12-tenant-portal-management) |
| Kubernetes Deployment | [KUBERNETES_GUIDE.md](KUBERNETES_GUIDE.md) |
| Security Guide | [SECURITY.md](SECURITY.md) |
| CHANGELOG — v1.84.x | [CHANGELOG.md](../CHANGELOG.md) |
