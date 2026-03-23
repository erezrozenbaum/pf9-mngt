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

- [x] **Docker Secrets support implemented** *(Phase J5)*
  - `api/secret_helper.py` reads from `/run/secrets/<name>` with env-var fallback
  - Production: populate `secrets/db_password`, `secrets/ldap_admin_password`,
    `secrets/pf9_password`, `secrets/jwt_secret` (see `secrets/README.md`)
  - Development: leave secret files empty — falls back to `.env` vars automatically
  - `secrets/*` is gitignored (only `secrets/README.md` is tracked)

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

## Email Notification Security

- [ ] **SMTP credentials secured**
  - `SMTP_PASSWORD` stored only in `.env` (never committed to git)
  - Use application-specific passwords where possible

- [ ] **SMTP TLS configured for external servers**
  - `SMTP_USE_TLS=true` for internet-facing SMTP servers
  - Internal relay servers (port 25, no auth) acceptable on trusted networks

- [ ] **From address validated**
  - `SMTP_FROM_ADDRESS` uses a domain you control
  - SPF/DKIM records configured if emails leave internal network

- [ ] **Notification RBAC verified**
  - `notifications:admin` permission restricted to Admin/Superadmin
  - Test email endpoint requires admin permission

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

- [x] **TLS termination via nginx** *(Phase C)*
  - HTTP (port 80) redirected to HTTPS (port 443)
  - HSTS, X-Frame-Options, X-Content-Type-Options headers added

- [x] **Production port hardening** *(Phase M2.2 / I.1)*
  - `docker-compose.prod.yml` sets `ports: []` for `pf9_api` (8000), `pf9_ui` (5173/80), and `pf9_monitoring` (8001)
  - Only nginx TLS proxy (80/443) is bound to host; all backend services are internal-only
  - Verify: `docker compose -f docker-compose.yml -f docker-compose.prod.yml ps` shows no 8000/8001/5173 host ports

- [x] **nginx prod config uses correct UI port** *(Phase M2.1)*
  - `nginx/nginx.prod.conf` proxies `pf9_ui:80` (production nginx build)
  - `docker-compose.prod.yml` bind-mounts `nginx.prod.conf` over the baked-in dev config
  - Dev `nginx/nginx.conf` unchanged (still proxies `pf9_ui:5173` for Vite dev server)

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

---

## Multi-Region & Multi-Cluster Security

### Before Adding a New Control Plane

- [ ] `auth_url` is HTTPS (not HTTP) for production control planes
- [ ] `auth_url` does NOT resolve to a private/RFC-1918 address (unless `allow_private_network` is explicitly required and approved by a superadmin)
- [ ] `allow_private_network` is `FALSE` in the INSERT statement — confirm with: `SELECT id, allow_private_network FROM pf9_control_planes;`
- [ ] `password_enc` is stored as `env:{sha256_prefix}` — NOT as a plaintext password. Confirm `left(password_enc, 4) = 'env:'`
- [ ] Credential is injected from a Docker secret or `.env` file, never hard-coded in SQL or application code

### Ongoing Multi-Cluster Health Checks

- [ ] `pf9_regions.health_status` is monitored; rows with `auth_failed` or `unreachable` require immediate credential rotation or network investigation
- [ ] `cluster_sync_metrics.error_count` is tracked; persistent errors indicate endpoint misconfiguration
- [ ] Cache keys verified to include `region_id` segment — check `api/cache.py` `_make_key()` method
- [ ] No `PF9_PASSWORD` value or control-plane credentials appear in application logs, API responses, or error messages
- [ ] `cluster_tasks` table is reviewed for stale tasks (status `pending` or `in_progress` for more than 24 hours)

### Per-Region RBAC (Future)

- [ ] When per-region RBAC is enabled: `user_roles.region_id IS NOT NULL` rows must be validated to reference real `pf9_regions.id` values
- [ ] Global roles (`user_roles.region_id IS NULL`) are reviewed quarterly to ensure least-privilege access
- [12 Factor App - Store config in environment](https://12factor.net/config)

---

## Kubernetes Deployment Security (v1.82.0+)

### Sealed Secrets

- [x] **No credential values in `values.yaml` or `values.prod.yaml`** *(v1.82.0)*
  - All sensitive values are referenced by Kubernetes Secret **name** only (e.g. `pf9-db-credentials`)
  - No passwords, API keys, or tokens appear in any committed Helm values file
  - Verify: `grep -r "password" k8s/helm/pf9-mngt/values.yaml` should return zero credential values

- [ ] **All nine Sealed Secrets created before `helm install`**
  - Follow the kubeseal commands in `k8s/sealed-secrets/README.md`
  - Required secrets: `pf9-db-credentials`, `pf9-jwt-secret`, `pf9-ldap-secrets`,
    `pf9-smtp-secrets`, `pf9-pf9-credentials`, `pf9-snapshot-creds`,
    `pf9-provision-creds`, `pf9-ssh-credentials`, `pf9-copilot-secrets`
  - Verify all exist before go-live: `kubectl get secrets -n pf9-mngt`

- [ ] **Sealed Secret blobs committed to git**
  - SealedSecret YAML files (`k8s/sealed-secrets/*.yaml`) are safe to commit — the encrypted
    blobs can only be decrypted by the Sealed Secrets controller in your cluster
  - Commit them to version-control so secrets can be recreated after cluster rebuild

- [ ] **Sealed Secrets controller cert backed up**
  - If the cluster is destroyed, the controller's private key is needed to re-seal
  - Backup: `kubectl get secret -n kube-system sealed-secrets-keyXXXX -o yaml > sealed-secrets-key-backup.yaml`
  - Store the backup file in a secure vault — **never commit it to git**

### Pod & Container Security

- [ ] **Pod security contexts set** *(Chart defaults enforce these)*
  - `runAsNonRoot: true` on all application pods
  - `allowPrivilegeEscalation: false`
  - `readOnlyRootFilesystem: true` where possible (workers write only to `/tmp` or `/backups`)
  - Verify: `kubectl get pods -n pf9-mngt -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.securityContext}{"\n"}{end}'`

- [ ] **Monitoring pod does NOT mount Docker socket**
  - The Kubernetes `monitoring` Deployment does not use `hostPath: /var/run/docker.sock`
  - Confirmed in `templates/monitoring/deployment.yaml` — Docker socket is Docker Compose only

- [x] **`PRODUCTION_MODE=true` always set in API pod** *(Chart enforces)*
  - The API `Deployment` hard-codes `PRODUCTION_MODE: "true"` in the environment
  - This cannot be changed via `values.yaml` — it is unconditional in the template

### Network Isolation

- [ ] **`pf9-ldap` Service is ClusterIP only**
  - LDAP port 389 must never be exposed outside the cluster
  - Verify: `kubectl get svc pf9-mngt-ldap -n pf9-mngt` — type should be `ClusterIP`

- [ ] **`pf9-db` Service is ClusterIP only**
  - PostgreSQL port 5432 must never be exposed outside the cluster
  - Verify: `kubectl get svc pf9-mngt-db -n pf9-mngt` — type should be `ClusterIP`

- [ ] **Ingress enforces TLS** (cert-manager ClusterIssuer must be Ready)
  - `kubectl describe clusterissuer letsencrypt-prod` — condition `Ready: True`
  - `kubectl describe certificate pf9-mngt-tls -n pf9-mngt` — `Ready: True`

### Secret Rotation on Kubernetes

To rotate a credential:

1. Generate the new value
2. Re-seal with kubeseal and update the corresponding `k8s/sealed-secrets/*.yaml`
3. `kubectl apply -f k8s/sealed-secrets/<secret>.yaml` — Sealed Secrets controller
   automatically updates the backing Kubernetes Secret
4. Restart impacted pods: `kubectl rollout restart deployment pf9-mngt-api -n pf9-mngt`
5. Commit the updated sealed blob to git
