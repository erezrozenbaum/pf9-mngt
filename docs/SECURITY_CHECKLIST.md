# Security Checklist

## Pre-Production Security Requirements

### Environment & Secrets Management

- [ ] **.env file is NOT committed to git**
  - Confirm `.env` is in `.gitignore`
  - Run: `git check-ignore -v .env` (should return `.gitignore:2:.env`)
  
- [ ] **.env.example exists as template** with placeholder values
  - No real passwords or API keys
  - All values are `<PLACEHOLDER>` format
  - Committed to git for reference

- [ ] **All credentials rotated after any exposure**
  - GitHub/GitGuardian detected exposed password
  - Immediately rotate in Platform9 console
  - Update local `.env`

### Database Security

- [ ] **Unique database password set**
  - Not the default `pf9_password_change_me`
  - 16+ characters with mixed case, numbers, symbols
  - Stored in `.env` (NOT committed)

- [ ] **pgAdmin credentials changed**
  - Not default admin@example.com/admin123
  - Stored in `.env`

### Platform9 API Credentials

- [ ] **Service account created in Platform9**
  - Dedicated account (not admin user)
  - Email: stored in `.env` as `PF9_USERNAME`
  - Password: stored in `.env` as `PF9_PASSWORD`

- [ ] **API credentials protected**
  - Only in `.env` file (ignored by git)
  - Never logged or exposed
  - Rotation procedure documented

### LDAP Configuration

- [ ] **LDAP admin password set**
  - Stored in `.env` as `LDAP_ADMIN_PASSWORD`
  - 12+ characters minimum

- [ ] **LDAP config password set**
  - Stored in `.env` as `LDAP_CONFIG_PASSWORD`
  - Different from admin password

- [ ] **LDAP Base DN set**
  - Stored in `.env` as `LDAP_BASE_DN`
  - Must match domain (e.g., `dc=company,dc=com` for `company.com`)
  - Required for container healthcheck to function

### Snapshot Encryption

- [ ] **Encryption key generated**
  - Stored in `.env` as `SNAPSHOT_PASSWORD_KEY`
  - Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

- [ ] **Service user password encrypted**
  - Stored in `.env` as `SNAPSHOT_USER_PASSWORD_ENCRYPTED`
  - Or plaintext in `SNAPSHOT_SERVICE_USER_PASSWORD`

- [ ] **Snapshot service user configured**
  - `SNAPSHOT_SERVICE_USER_EMAIL` set in `.env` (your snapshot service user email)
  - User pre-created in Platform9 (Identity → Users)
  - Password provided via plaintext or Fernet encryption
  - Verify: `docker logs pf9_snapshot_worker 2>&1 | grep SERVICE_USER`

- [ ] **Service user password can be decrypted**
  - Test: `python -c "from snapshots.snapshot_service_user import get_service_user_password; print('OK', len(get_service_user_password()))"`

### Snapshot Restore Security

- [ ] **Restore feature disabled by default**
  - `RESTORE_ENABLED` is `false` unless explicitly needed
  - Only enable in environments where VM restore is an approved workflow

- [ ] **REPLACE mode restricted to superadmin**
  - Verify in `role_permissions`: only superadmin has `restore:admin`
  - REPLACE mode requires superadmin role AND destructive confirmation string

- [ ] **Dry-run mode tested first**
  - Set `RESTORE_DRY_RUN=true` and run a test restore before enabling real execution
  - Validates planning logic without modifying infrastructure

- [ ] **Volume cleanup policy decided**
  - `RESTORE_CLEANUP_VOLUMES=false` (default) keeps orphaned volumes for inspection
  - Set to `true` only if you prefer automatic cleanup of failed restore volumes

## Container Security

### Volume Protection

- [ ] **Docker volumes excluded from git**
  - `pgdata/` - Database files
  - `ldap_data/` - User directory
  - `app_logs/` - Application logs
  - All in `.gitignore`

- [ ] **Reports directory protected**
  - `C:\Reports\Platform9\` not in git
  - Contains generated data, never committed

### Network Security

- [ ] **TLS verification enabled**
  - `PF9_VERIFY_TLS=true` in `.env`
  - Except in dev/testing environments

- [ ] **ALLOWED_ORIGIN configured**
  - `PF9_ALLOWED_ORIGIN=https://your-domain.com`
  - Only allows specified origin for CORS

### Log Security

- [ ] **Logs not exposed in git**
  - `*.log` files in `.gitignore`
  - Log files written to `/app/logs` volume

- [ ] **Sensitive data not logged**
  - Passwords masked in output
  - API keys not included in logs
  - PII handled according to regulations

## Deployment Security

### Initial Deployment

1. **Copy `.env.example` to `.env`**
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env` with production values**
   - Replace all `<PLACEHOLDER>` values
   - Use strong random passwords
   - Use actual API credentials

3. **Verify `.env` is ignored**
   ```bash
   git status  # Should NOT show .env
   ```

4. **Start containers**
   ```bash
   docker compose up -d
   ```

### Ongoing Security

- [ ] **Regular password rotation**
  - Every 90 days minimum
  - Immediately after any exposure

- [ ] **Git history cleanup**
  - If secrets accidentally committed, use `git filter-branch`
  - Force push only after careful review
  - Notify team of rebase

- [ ] **Credential audit**
  - Monitor GitHub Security logs
  - Review exposed secrets alerts
  - Rotate immediately if found

- [ ] **Access control**
  - Only authorized users have `.env` access
  - Database backups encrypted
  - API tokens rotated regularly

## Compliance & Auditing

- [ ] **Audit logging enabled**
  - All API requests logged
  - User actions tracked in database
  - Logs retained for 90+ days

- [ ] **Data retention policy**
  - Snapshot runs retained 1 year
  - Compliance reports retained 1 year
  - Logs rotated after 30 days

- [ ] **Encryption standards**
  - Database connections use TLS
  - Backup files encrypted
  - Credentials encrypted at rest

## Incident Response

### If credentials are exposed:

1. **Assess exposure scope**
   - What was exposed (password, API key, token)?
   - When was it exposed?
   - Who has access?

2. **Rotate immediately**
   - Change password in source system
   - Update `.env` locally
   - Rebuild containers

3. **Remediate git history**
   ```bash
   # After careful review only:
   git filter-branch --force --index-filter \
     'git rm --cached --ignore-unmatch .env' \
     --prune-empty --tag-name-filter cat -- --all
   git push --force --all
   git push --force --tags
   ```

4. **Notify team**
   - Alert all developers
   - Require password reset
   - Review git logs

5. **Document incident**
   - What was exposed
   - When discovered
   - Action taken
   - Prevention measures

## References

- [OWASP Secret Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
- [GitHub Secret Scanning](https://docs.github.com/en/code-security/secret-scanning)
- [12 Factor App - Store config in environment](https://12factor.net/config)
