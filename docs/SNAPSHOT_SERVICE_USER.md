# Snapshot Service User Management

## Overview

This document describes the **Snapshot Service User** feature that enables snapshots to be created in the correct tenant project instead of the service domain.

## Problem Statement

When using the admin session to create snapshots, Platform9's OpenStack API always creates resources in the authenticated session's project scope, which is the **service domain**. The `all_tenants=1` parameter only allows **listing** resources across tenants; it doesn't change where resources are created.

To create snapshots in the correct tenant project, we need a user account with admin privileges in that specific tenant.

## Solution Architecture

### Pre-Existing Service User

A dedicated service account must be **pre-created in Platform9** before deployment. The system does **not** auto-create this user — it only manages role assignments and authentication.

- **Email**: Configured via `SNAPSHOT_SERVICE_USER_EMAIL` environment variable
- **Role**: `admin` (assigned per-project automatically by the system)
- **Scope**: One user, granted admin on each tenant project as needed
- **Domain**: Default domain (configurable via `SNAPSHOT_SERVICE_USER_DOMAIN`)

### Dual-Session Architecture

The snapshot system uses two separate sessions:

1. **Admin Session** — Scoped to the service project
   - Used for listing volumes (`all_tenants=1`), listing snapshots, and cleanup
   - Token scope: service project (e.g., `service` in `Default` domain)

2. **Service User Session** — Scoped to each volume's tenant project
   - Used for creating snapshots in the correct tenant
   - Authenticated as the snapshot service user with project-scoped token
   - Falls back to admin session if service user is unavailable

### Password Management

The service user password can be provided in two ways:

1. **Plaintext** (simpler): Set `SNAPSHOT_SERVICE_USER_PASSWORD` in `.env`
2. **Fernet Encrypted** (more secure): Set both `SNAPSHOT_PASSWORD_KEY` and `SNAPSHOT_USER_PASSWORD_ENCRYPTED`

The system tries plaintext first, then falls back to Fernet decryption.

## Implementation Details

### Module: `snapshots/snapshot_service_user.py`

**Exports:**
- `SERVICE_USER_EMAIL` — The configured service user email address
- `ensure_service_user(admin_session, keystone_url, project_id)` — Ensures admin role on project
- `get_service_user_password()` — Retrieves password (plaintext or decrypted)
- `reset_cache()` — Clears per-run role and user ID caches

**Internal Functions:**
- `_find_user_id(session, keystone_url, email)` — Looks up user by email in Keystone
- `_find_role_id(session, keystone_url, role_name)` — Finds role ID by name
- `_has_role_on_project(session, keystone_url, user_id, project_id, role_id)` — Checks existing role assignment (HEAD request, 204=exists)
- `_assign_role_to_project(session, keystone_url, user_id, project_id, role_id)` — Assigns role via PUT

**Caching:**
- `_cached_user_id` — User ID cached after first lookup (avoids repeated Keystone queries)
- `_role_cache` — Dict of `project_id → True` for projects already verified this run

### Integration: `snapshots/p9_auto_snapshots.py`

The main auto-snapshot loop groups volumes by project, then for each project:

```python
# 1. Ensure service user has admin role on the project
ensure_service_user(admin_session, keystone_url, vol_project_id)

# 2. Authenticate as service user scoped to the project
svc_sess, svc_tok = get_service_user_session(
    vol_project_id, SERVICE_USER_EMAIL, service_password, user_domain="default"
)

# 3. Use service user session for snapshot creation
process_volume(
    admin_session=session,            # For listing / cleanup
    admin_project_id=admin_project_id,
    create_session=svc_sess,          # For creating snapshots
    create_project_id=vol_project_id, # Matches service user token scope
    ...
)
```

**Fallback Chain:**
1. Service user session scoped to volume's project (correct tenant)
2. Admin session scoped to admin project (snapshots land in service domain)

### Environment Variables

```bash
# Service user identity
SNAPSHOT_SERVICE_USER_EMAIL=<your-snapshot-user@your-domain.com>    # User email (must exist in Platform9)
SNAPSHOT_SERVICE_USER_DOMAIN=default                   # User domain ID

# Password (Option A: plaintext)
SNAPSHOT_SERVICE_USER_PASSWORD=<password>

# Password (Option B: Fernet encrypted)
SNAPSHOT_PASSWORD_KEY=<Fernet key>                     # Generated with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
SNAPSHOT_USER_PASSWORD_ENCRYPTED=<encrypted password>  # Generated with: python -c "from cryptography.fernet import Fernet; f=Fernet(b'<key>'); print(f.encrypt(b'<password>').decode())"

# Disable service user (use admin session only)
SNAPSHOT_SERVICE_USER_DISABLED=false                   # Set to "true" to disable
```

## Setup Guide

### Prerequisites

1. **Create the service user** in Platform9 UI or CLI:
   - Navigate to Identity → Users → Create User
   - Email: Your chosen service user email
   - Domain: Default
   - Set a strong password (32+ characters recommended)

2. The system will **automatically** assign admin role to this user on each tenant project as snapshots are processed.

### Configure Password (Option A: Plaintext)

```bash
# Add to .env
SNAPSHOT_SERVICE_USER_EMAIL=<your-snapshot-user@your-domain.com>
SNAPSHOT_SERVICE_USER_PASSWORD=<your-service-user-password>
```

### Configure Password (Option B: Fernet Encrypted)

```bash
# Generate encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Output: <your-generated-fernet-key>

# Encrypt the password (replace <YOUR_KEY> with the key from above)
python -c "from cryptography.fernet import Fernet; f=Fernet(b'<YOUR_KEY>'); print(f.encrypt(b'<YOUR_PASSWORD>').decode())"

# Add to .env
SNAPSHOT_SERVICE_USER_EMAIL=<your-snapshot-user@your-domain.com>
SNAPSHOT_PASSWORD_KEY=<your-generated-fernet-key>
SNAPSHOT_USER_PASSWORD_ENCRYPTED=<your-encrypted-password>
```

### Verify Configuration

```bash
# Test password retrieval
python -c "
from snapshots.snapshot_service_user import get_service_user_password, SERVICE_USER_EMAIL
pw = get_service_user_password()
print(f'User: {SERVICE_USER_EMAIL}')
print(f'Password length: {len(pw)}')
print('OK')
"
```

## Security Considerations

### Strengths

- **Minimal privilege**: Admin role assigned only to projects that need snapshots
- **Per-run caching**: Role checks cached within a run to avoid repeated Keystone API calls
- **Encrypted password option**: Fernet symmetric encryption for `.env` storage
- **Graceful fallback**: System continues with admin session if service user fails
- **Disable switch**: Set `SNAPSHOT_SERVICE_USER_DISABLED=true` to disable entirely

### Recommendations

1. **Protect `.env` file**:
   ```powershell
   # Windows
   icacls .env /inheritance:r /grant:r "%USERNAME%:F"
   ```
   ```bash
   # Linux/macOS
   chmod 600 .env
   ```

2. **Use encrypted password** in production (Option B above)

3. **Audit role assignments**: Monitor `[SERVICE_USER]` log entries for unexpected role grants

4. **Rotate password periodically**: Update in both Platform9 and `.env`

## Troubleshooting

### Service user not found

**Error**: `Service user '<email>' not found in Keystone`

**Cause**: User does not exist in Platform9

**Fix**: Create the user in Platform9 UI (Identity → Users → Create User)

### Password decryption fails

**Error**: `Failed to decrypt password`

**Causes**:
- Encryption key (`SNAPSHOT_PASSWORD_KEY`) changed or corrupted
- Encrypted password (`SNAPSHOT_USER_PASSWORD_ENCRYPTED`) manually modified
- `cryptography` package not installed

**Fix**:
1. Install cryptography: `pip install cryptography`
2. Re-generate key and encrypted password (see Setup Guide above)
3. Update `.env` with new values

### Role assignment fails

**Error**: `Failed to assign admin role to <email> on project <id>`

**Cause**: Admin session lacks permission to manage roles in the target project

**Fix**: Ensure the admin user (`PF9_USERNAME`) has domain-level admin privileges

### Snapshots still in service domain

**Symptom**: Snapshots created but in wrong project

**Check**:
```bash
docker logs pf9_snapshot_worker 2>&1 | grep SERVICE_USER
```

**Expected output** (working):
```
[SERVICE_USER] <your-snapshot-user@your-domain.com> already has admin role on project <id>
Using service user session for project <name>
```

**If you see fallback messages**: Check password configuration and Keystone connectivity

## References

- [Snapshot Automation Guide](SNAPSHOT_AUTOMATION.md) — Full snapshot system documentation
- [Security Checklist](SECURITY_CHECKLIST.md) — Security hardening recommendations
- [Deployment Guide](DEPLOYMENT_GUIDE.md) — Deployment configuration
- [Fernet Encryption](https://cryptography.io/en/latest/fernet/) — Cryptography library docs
