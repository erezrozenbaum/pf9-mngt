# Tenant Self-Service Portal — Operator Guide

**Version**: 1.85.12  
**Last Updated**: April 19, 2026  
**Audience**: Platform administrators enabling and managing the tenant self-service portal

---

## Overview

The tenant self-service portal is a completely isolated web application that lets your Platform9 end-customers (tenants) view and manage their own infrastructure without exposing the admin panel.

**What tenants can do:**
- View their own VMs, volumes, and snapshots
- View and manage networks (subnets, CIDRs, DHCP, shared/external flags)
- View security groups, add / delete inbound and outbound rules inline
- Explore resource relationships via the SVG Dependency Graph (VM ↔ Network ↔ SG)
- Provision new VMs (1–10 at a time): select flavor, image, network, security groups, cloud-init data
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

Open **Admin Tools → 🏢 Tenant Portal → Access Management**, enter the Control Plane ID, then click **+ Grant Access**. Fill in:

| Field | Required | Description |
|---|---|---|
| Keystone User ID | ✅ Yes | The Keystone UUID for the user |
| User Name | No | Friendly display name shown in the table (e.g. "John Smith") |
| Tenant / Org Name | No | Customer or org label (e.g. "Acme Ltd") |
| Notes | No | Free-text admin note |
| Require MFA | No | Checkbox — enforces TOTP on next login |

Alternatively, use the API directly (see Step 3).

### Step 3 — Grant access via API

```bash
curl -X PUT https://<admin-host>/api/admin/tenant-portal/access \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "keystone_user_id": "<uid>",
    "user_name": "John Smith",
    "control_plane_id": "<cp_id>",
    "tenant_name": "Acme Ltd",
    "enabled": true,
    "mfa_required": true
  }'
```

### Step 4 — Configure branding (optional but recommended)

```bash
curl -X PUT https://<admin-host>/api/admin/tenant-portal/branding/<cp_id> \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "company_name": "Customer Infrastructure Portal",
    "logo_url": "https://cdn.customer.com/logo.png",
    "favicon_url": "https://cdn.customer.com/favicon.ico",
    "primary_color": "#1A73E8",
    "accent_color": "#2563eb",
    "support_email": "support@customer.com",
    "welcome_message": "Welcome to your infrastructure portal"
  }'
```

Branding is fetched by the tenant-ui on load from `GET /tenant/branding` (unauthenticated, 60 s cache). If no branding row exists, safe defaults are returned (`company_name: "Cloud Portal"`, `primary_color: #1A73E8`, `accent_color: #F29900`).

### Step 5 — Send the portal URL to the customer

| Deployment | URL |
|------------|-----|
| Docker Compose (dev) | `http://localhost:8083/` |
| Docker Compose (dev Vite) | `http://localhost:8082/` |
| Kubernetes | `https://<tenant-portal-domain>/` (your `nginx-ingress-tenant` hostname) |

The customer authenticates with their **Platform9 Keystone credentials** (email + password + domain). The login form has three fields:

| Field | Description | Default |
|-------|-------------|---------|
| **Username** | Keystone user email (e.g. `org1@org1.com`) | — |
| **Password** | Keystone password | — |
| **Domain** | Keystone identity domain (same as the **Domain** field on the Platform9 login page) | `Default` |

> Most users are in the `Default` domain and can leave this field as-is. Users in a non-default Keystone domain must enter their domain name exactly as configured in Keystone (case-sensitive).

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

### Revoke all sessions for a specific user

```bash
curl -X DELETE https://<admin-host>/api/admin/tenant-portal/sessions/<cp_id>/<keystone_user_id> \
  -H "Authorization: Bearer <admin_token>"
# Terminates all active Redis sessions for the user immediately
# Their next request returns 401
```

To force re-auth across all users, repeat per user or restart the tenant portal service.

Sessions are automatically invalidated when:
- The user's IP address changes mid-session (IP binding, configurable)
- Access is revoked via the admin API
- The JWT TTL expires (configurable, default 480 minutes)
- Admin explicitly calls the DELETE sessions endpoint

---

## Branding Configuration

| Field | Type | Notes |
|-------|------|-------|
| `company_name` | string | Displayed in the portal title bar and login screen |
| `logo_url` | URL string or null | HTTPS URL or base64 data URL; displayed top-left in tenant-ui. Logos uploaded via the admin UI's **Upload Image** button are stored as inline data URLs and are self-contained. Legacy file-path values (created before v1.85.9) are automatically converted to data URLs by `GET /tenant/branding` using the shared `branding_logos` volume. |
| `favicon_url` | URL string or null | Optional; falls back to pf9-mngt default favicon |
| `primary_color` | `#rrggbb` | Primary UI colour (default `#1A73E8`) |
| `accent_color` | `#rrggbb` | Accent colour for highlights and buttons (default `#F29900`); validated as hex |
| `support_email` | email or null | Optional support contact shown in the portal |
| `support_url` | URL or null | Optional support link |
| `welcome_message` | string or null | Shown on the portal login/dashboard screen |
| `footer_text` | string or null | Displayed in the tenant-ui footer |

The branding endpoint (`GET /tenant/branding`) is **unauthenticated** — it must be accessible before login so the login page can display customer branding. The 60-second in-process cache prevents DB pressure during high traffic.

The admin UI's **Branding** sub-tab provides a form with fields for all branding properties plus an **Upload Image** button for logo uploads. Save with the **Save Branding** button.

---

## MFA Configuration

### MFA decision logic

Whether MFA is required for a given login is decided by **two independent controls**:

| Control | Where set | Effect |
|---------|-----------|--------|
| `mfa_required` per-user flag | Admin UI → Tenant Portal → Access Management → Grant/Edit | MFA required for this user when `true` |
| `TENANT_MFA_MODE` env var on the pod | `values.yaml` → `tenantPortal.config.mfaMode` | Global kill-switch: set to `none` to disable MFA cluster-wide regardless of per-user flags |

The effective rule is: **`mfa_required = access_row.mfa_required AND TENANT_MFA_MODE != "none"`**

This means:
- An admin can grant a user access *without* MFA by leaving the "Require MFA" checkbox unchecked, even when `TENANT_MFA_MODE=email_otp`.
- Setting `TENANT_MFA_MODE=none` disables MFA for all users without changing any DB rows.
- Setting `TENANT_MFA_MODE=email_otp` or `totp` does **not** force MFA on users whose `mfa_required` flag is `false`.

Two MFA methods are supported (when enabled):

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

This action is also available in the Admin UI → Tenant Portal → **Access Management** sub-tab — click the **Reset MFA** button in the Actions column for the user row. It creates a full audit log entry.

---

## Audit Log

Every tenant API call writes an immutable entry to `tenant_action_log` — atomically with the data query.

```bash
GET /api/admin/tenant-portal/audit/<cp_id>?limit=100&offset=0&keystone_user_id=<uid>
```

Supported query params: `limit` (1–500, default 50), `offset`, `keystone_user_id` (optional filter). Response includes `total`, `offset`, `limit`, and `items`.

Captured fields per entry:
- `keystone_user_id` (Keystone user ID)
- `action` (e.g. `list_vms`, `restore_execute`, `view_snapshot`)
- `resource_type` / `resource_id` (if applicable)
- `project_id` / `region_id` (if applicable)
- `ip_address`
- `created_at`
- `success` (boolean)

The audit log is available in the Admin UI → Tenant Portal → **Audit Log** sub-tab with pagination (50 entries per page).

---

## What Tenants See — The 10 Screens *(v1.91.0)*

| Screen | Description |
|--------|-------------|
| **Health Overview** *(default)* | Three circular dials: Efficiency score (resource utilisation quality), Stability score (open insight severity), Capacity Runway (days until first quota exhaustion). Sourced from `GET /tenant/client-health` → admin API. |
| **Dashboard** | Overview cards: VM count, running VMs, storage usage, snapshot compliance %, active restore jobs |
| **Infrastructure** | VM list with status, spec, volumes; volume list with attachment status |
| **Snapshot Coverage** | 30-day calendar showing which VMs had snapshots each day; compliance % per VM |
| **Monitoring** | Per-VM metrics (CPU, RAM), 7-day and 30-day availability % |
| **Restore Center** | 3-step wizard: select snapshot → review plan → confirm restore. Job list with live progress. All restores are side-by-side (non-destructive). **Observer accounts can view but cannot execute restores.** |
| **Runbooks** | Read-only catalogue of runbooks you have published to the tenant. **Observer accounts can view but cannot execute runbooks.** |
| **Reports** | Exportable resource and compliance reports |
| **New VM 🚀** | Self-service VM provisioning form (name, image, flavour, network, cloud-init). **Observer accounts cannot access this screen.** |
| **Activity Log** | Filterable table of the tenant's own portal actions with timestamps, resource references, and response status |

---

## Observer Role (Read-Only Access) *(v1.91.0)*

The `portal_role` field on each access grant controls whether a user is a **manager** (full access, the default) or an **observer** (read-only).

### What observers can do
- View all read-only screens: Health Overview, Dashboard, Infrastructure, Snapshot Coverage, Monitoring, Activity Log, Reports.
- Browse runbook catalogue and restore history.
- Call any `GET` endpoint in the tenant portal.

### What observers cannot do
- Execute runbooks (`POST /tenant/runbooks/{name}/execute`).
- Create, cancel, or execute restore jobs.
- Provision VMs (`POST /tenant/vms`).
- Add or delete security group rules.
- Trigger sync-and-snapshot.

Attempting any write action returns HTTP 403 `observer_role_cannot_write`.

### Granting observer access — Admin UI

1. Open **Admin → 🏢 Tenant Portal → Access Management**.
2. Find the user row and click **→ Observer** in the Role column.
3. The role badge turns amber immediately. The user's next login (or token refresh) will carry the new role.

### Granting observer access — API

```bash
PUT /api/admin/tenant-portal/access
{
  "control_plane_id": "<cp_id>",
  "keystone_user_id": "<user_id>",
  "project_ids": ["<proj_id>"],
  "portal_role": "observer"
}
```

### Inviting a new observer by email

```bash
POST /api/intelligence/invite-observer
Authorization: Bearer <admin_token>

{
  "control_plane_id": "<cp_id>",
  "project_id": "<proj_id>",
  "invited_email": "guest@example.com",
  "created_by": "admin"
}
```

The API generates a single-use token, inserts a `portal_invite_tokens` row (expires in 72 hours), and sends a branded HTML email with a magic login link. The invited user does not need a pre-existing account — they complete registration when they follow the link.

### Reverting to manager

In the Admin UI click **→ Manager** on the user row, or call the same `PUT /api/admin/tenant-portal/access` endpoint with `"portal_role": "manager"`.

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
