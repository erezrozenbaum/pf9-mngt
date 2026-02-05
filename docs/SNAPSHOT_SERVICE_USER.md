# Snapshot Service User Management

## Overview

This document describes the **Snapshot Service User** feature—a workaround that enables snapshots to be created in the correct tenant instead of the service domain.

## Problem Statement

When using the admin session to create snapshots, Platform9's OpenStack API always creates resources in the authenticated session's project scope, which is the **service domain**. The `all_tenants=1` parameter only allows **listing** resources across tenants; it doesn't change where resources are created.

To create snapshots in the correct tenant project, we need a user account with privileges in that specific tenant.

## Solution Architecture

### Automatic Service User Creation

A dedicated service account (`snapshotsrv@ccc.co.il`) is automatically created in each tenant with the following properties:

- **Email**: snapshotsrv@ccc.co.il
- **Role**: service (Platform9 service role with snapshot permissions)
- **Scope**: One user per tenant (Default domain)
- **Lifecycle**: Temporary until Platform9 enables cross-tenant admin access

### Auto-Generated & Encrypted Password

The service user password is:

1. **Auto-generated** on first run using `secrets` module (32 random characters)
2. **Encrypted** using Fernet symmetric encryption
3. **Stored encrypted** in `.env` as `SNAPSHOT_USER_PASSWORD_ENCRYPTED`
4. **Never in plaintext** on disk or in memory (except during authentication)
5. **Unknown to administrators** (security by design)

### Encryption Key Management

- **Key generation**: Fernet key generated on first run
- **Key storage**: Stored in `.env` as `SNAPSHOT_PASSWORD_KEY`
- **Key access**: Only the running process with access to `.env` can decrypt
- **Rotation**: Can be rotated by updating both key and password

## Implementation Details

### Modules

**`snapshot_service_user.py`** - Service user management utilities

Functions:
- `generate_secure_password()` - Generate cryptographically secure password
- `get_or_create_encryption_key()` - Manage encryption key lifecycle
- `encrypt_password()` / `decrypt_password()` - Fernet encryption/decryption
- `get_service_user_password()` - Get/generate service user password
- `ensure_service_user()` - Check/create user in tenant and assign role
- `get_service_user_session()` - Authenticate as service user

### Integration Points

**`snapshots/p9_auto_snapshots.py`** - Calls `ensure_service_user()` before creating snapshots

```python
# Before each snapshot run, ensure service user exists in the project
ensure_service_user(session, keystone_url, project_id)

# Use service user session for snapshot operations
service_session = get_service_user_session(keystone_url)
cinder_create_snapshot(service_session, volume_id, ...)
```

### Environment Variables

Added to `.env` and `.env.template`:

```bash
# Auto-generated on first run
SNAPSHOT_PASSWORD_KEY=<Fernet encryption key>
SNAPSHOT_USER_PASSWORD_ENCRYPTED=<Encrypted password>
```

## Usage

### Automatic (During Snapshot Runs)

The service user is automatically created and used:

```bash
python snapshots/p9_auto_snapshots.py --policy daily_5
```

The script will:
1. Check if `snapshotsrv@ccc.co.il` exists in each tenant
2. If not, create it with auto-generated password
3. Assign `service` role to the tenant project
4. Use this user for all snapshot operations
5. Return snapshots created in the correct tenant

### Manual Testing

```bash
# Test the module
python snapshot_service_user.py

# Output:
# [TEST] Service user email: snapshotsrv@ccc.co.il
# [TEST] Password generated (length: 32)
# [TEST] Encryption key ready
# [TEST] Module ready for use
```

## Security Considerations

### Strengths

✅ **No plaintext passwords** on disk  
✅ **Unknown to administrators** (auto-generated)  
✅ **Limited scope** (per-tenant service user, not global admin)  
✅ **Service role** (narrower permissions than admin)  
✅ **Encrypted storage** using industry-standard Fernet  
✅ **Audit trail** (can log user creation events to database)  

### Limitations

⚠️ **One password per tenant** (can't easily rotate individual passwords)  
⚠️ **Encryption key in .env** (protect .env file with appropriate permissions)  
⚠️ **Service account accessible** (anyone with .env can decrypt)  
⚠️ **Temporary solution** (depends on Platform9 limitation)  

### Recommendations

1. **Protect .env file**
   ```bash
   chmod 600 .env  # Linux/macOS
   icacls .env /inheritance:r /grant:r "%USERNAME%:F"  # Windows
   ```

2. **Audit user creation**
   - Log all `snapshotsrv@ccc.co.il` creation events to database
   - Monitor for unexpected role assignments

3. **Document password removal**
   - Document how to delete these users when Platform9 enables cross-tenant admin
   - Create automation for bulk deletion

4. **Separate authentication**
   - Consider using a separate encryption key file (not in .env)
   - Example: `/etc/pf9-mgmt/snapshot_key.txt` with restricted permissions

## Cleanup & Deprecation

When Platform9 enables cross-tenant admin access:

1. **Stop creating service users**
   - Set environment variable: `SNAPSHOT_SERVICE_USER_DISABLED=true`
   - Comment out `ensure_service_user()` calls

2. **Delete existing service users**
   ```bash
   python snapshots/cleanup_service_users.py --all
   # Deletes snapshotsrv@ccc.co.il from all tenants
   ```

3. **Remove credentials**
   - Remove `SNAPSHOT_PASSWORD_KEY` and `SNAPSHOT_USER_PASSWORD_ENCRYPTED` from .env
   - Remove `snapshot_service_user.py`

4. **Revert to admin session**
   - Use original admin session for all snapshot operations
   - Snapshots will be created in the correct tenant automatically

## Troubleshooting

### Service user not created

**Issue**: `[ERROR] Failed to create service user`

**Causes**:
- Admin user doesn't have permission to create users in tenant
- Keystone API is unavailable
- User already exists with different configuration

**Solution**:
```bash
# Check if user exists
python -c "from snapshot_service_user import user_exists_in_domain; ..."
# Manually create user via Platform9 UI
# Re-run snapshot script to detect existing user
```

### Password decryption fails

**Issue**: `[WARNING] Failed to decrypt password`

**Causes**:
- Encryption key changed or corrupted
- Password was manually modified in .env

**Solution**:
1. Backup current .env
2. Remove corrupted lines:
   ```bash
   SNAPSHOT_PASSWORD_KEY=...
   SNAPSHOT_USER_PASSWORD_ENCRYPTED=...
   ```
3. Re-run script to generate new password and key

### Authentication fails

**Issue**: Service user created but authentication fails

**Causes**:
- Role assignment failed (insufficient permissions)
- User not yet synced across OpenStack services
- Password contains special characters causing issues

**Solution**:
```bash
# Check role assignment
openstack role assignment list --user snapshotsrv@ccc.co.il

# Verify user exists
openstack user list --domain Default

# Retry authentication after 30 seconds
sleep 30 && python snapshots/p9_auto_snapshots.py --policy daily_5
```

## References

- Platform9 documentation on user management
- OpenStack Keystone API reference
- Fernet encryption: https://cryptography.io/en/latest/fernet/
