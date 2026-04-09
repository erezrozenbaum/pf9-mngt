# secrets/

This directory holds Docker secret files that are bind-mounted into the API
container at `/run/secrets/<name>` at runtime.

**These files MUST NOT be committed to version control.**
The directory itself is covered by .gitignore.

## Development (docker-compose.yml)

Leave each file **empty**. The API will fall back to the corresponding
environment variable in your `.env` file automatically.

## Production (docker-compose.prod.yml)

Populate each file with the real secret value (single line, no trailing newline):

```bash
printf 'your-db-password'       > secrets/db_password
printf 'your-ldap-admin-pass'   > secrets/ldap_admin_password
printf 'your-pf9-api-password'  > secrets/pf9_password
python -c "import secrets; print(secrets.token_urlsafe(48), end='')" > secrets/jwt_secret
```

## Secret → Environment variable mapping

| Secret file            | Fallback env var      | Used by                        |
|------------------------|-----------------------|--------------------------------|
| `db_password`          | `PF9_DB_PASSWORD`     | `api/db_pool.py`               |
| `ldap_admin_password`  | `LDAP_ADMIN_PASSWORD` | `api/auth.py`                  |
| `pf9_password`         | `PF9_PASSWORD`        | `api/pf9_control.py`           |
| `jwt_secret`           | `JWT_SECRET_KEY`      | `api/auth.py`                  |
| `ldap_sync_key`        | `LDAP_SYNC_KEY`       | `api/auth.py`, `ldap_sync_worker/` |
| `vm_provision_key`     | `VM_PROVISION_KEY`    | `api/vm_provisioning_routes.py` — Fernet key for `os_password` at rest |
| `smtp_config_key`      | `SMTP_CONFIG_KEY`     | `api/smtp_helper.py`, `api/notification_routes.py` — Fernet key for `smtp.password` at rest |
