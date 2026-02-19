# Platform9 Management System — Linux Deployment Guide

**Version**: 1.0  
**Date**: February 2026  
**Status**: Production-Ready  
**Scope**: Running pf9-mngt on Linux (Ubuntu/Debian, RHEL/CentOS, or any Docker-capable distribution)

---

## Overview

pf9-mngt was developed on Windows with Docker containers. Since all 11 services run inside standard Linux-based Docker containers, the application itself is fully cross-platform. The only Windows-specific components are the **host-level automation scripts** (PowerShell + Task Scheduler) that handle metrics collection and inventory sync outside of Docker.

This guide covers what you need to change — and what you don't — when deploying on Linux.

### What Works Identically on Linux

| Component | Notes |
|-----------|-------|
| **docker-compose.yml** | 100% platform-agnostic. No changes needed. |
| **All 11 Docker services** | All use Linux base images already. |
| **.env configuration** | No Windows-specific paths or values. |
| **Database schema & migrations** | Identical. |
| **API, UI, Monitoring** | No OS-specific code. |
| **Worker services** (snapshot, backup, metering, notification) | Fully containerized, no host dependencies. |

### What Needs Linux Equivalents

| Windows Component | Linux Equivalent | Effort |
|-------------------|------------------|--------|
| `deployment.ps1` (993 lines) | Manual setup or `startup.sh` (below) | Medium |
| `startup.ps1` (262 lines) | `startup.sh` (below) | Low |
| `fix_monitoring.ps1` (57 lines) | One cron entry | Trivial |
| `setup_ldap.ps1` (206 lines) | `ldap/setup.sh` already exists | None |
| `release.ps1` (166 lines) | Git commands (shell-agnostic) | Trivial |
| Windows Task Scheduler tasks | cron entries (below) | Low |

---

## Prerequisites

### Docker & Docker Compose

#### Ubuntu / Debian

```bash
# Install Docker
sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Add your user to the docker group (avoids sudo for every docker command)
sudo usermod -aG docker $USER
newgrp docker

# Verify
docker --version
docker compose version
```

#### RHEL / CentOS / Rocky Linux

```bash
sudo dnf install -y dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

### Python 3 (for host scripts)

The host-side metrics collector and RVTools sync scripts run outside Docker. They need Python 3.9+ and a few packages.

```bash
# Ubuntu / Debian
sudo apt install -y python3 python3-pip python3-venv

# RHEL / CentOS
sudo dnf install -y python3 python3-pip
```

---

## Step-by-Step Deployment

### 1. Clone the Repository

```bash
cd /opt  # or wherever you want to install
git clone https://github.com/erezrozenbaum/pf9-mngt.git
cd pf9-mngt
```

### 2. Create Required Directories

```bash
mkdir -p logs secrets reports api/__pycache__ monitoring/cache pf9-ui/dist backups
```

### 3. Initialize Metrics Cache

```bash
cat > metrics_cache.json << 'EOF'
{"vms": [], "hosts": [], "alerts": [], "summary": {"total_vms": 0, "total_hosts": 0, "total_alerts": 0}, "timestamp": null}
EOF
```

### 4. Set Up Python Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install requests aiohttp openpyxl psycopg2-binary cryptography python-dotenv
```

### 5. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` with your values. At minimum, set these critical variables (the application will fail to start if they are empty or placeholder values):

```bash
# Required — must not be empty or <placeholder>
POSTGRES_PASSWORD=your-strong-db-password
LDAP_ADMIN_PASSWORD=your-ldap-admin-password
PGADMIN_PASSWORD=your-pgadmin-password
DEFAULT_ADMIN_PASSWORD=your-portal-admin-password

# Platform9 API credentials
PF9_USERNAME=your-pf9-user
PF9_PASSWORD=your-pf9-password
PF9_AUTH_URL=https://your-pf9-controller:5000/v3

# Monitoring — comma-separated PF9 hypervisor IPs
PF9_HOSTS=10.0.1.10,10.0.1.11,10.0.1.12

# JWT secret (generate a random key)
JWT_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
```

See `.env.example` for the complete list of available configuration options (SMTP, snapshots, metering, backup, restore, etc.).

### 6. Collect Initial Metrics

```bash
source .venv/bin/activate
python3 host_metrics_collector.py --once
```

This populates `monitoring/cache/metrics_cache.json` so the monitoring service has data on first startup.

### 7. Start All Services

```bash
docker compose up -d --build
```

Wait ~15-20 seconds, then verify:

```bash
docker compose ps
```

All services should show `Up` or `healthy`.

### 8. Verify Services

```bash
# API
curl -s http://localhost:8000/docs | head -5

# Monitoring
curl -s http://localhost:8001/health

# UI
curl -s -o /dev/null -w "%{http_code}" http://localhost:5173
```

### 9. Initialize LDAP Directory

The LDAP container auto-initializes on first start, but to create the RBAC groups and default users:

```bash
# The bash equivalent already exists in the project:
chmod +x ldap/setup.sh
./ldap/setup.sh
```

### 10. Run Database Migrations

The `init.sql` script runs automatically on first PostgreSQL start. For subsequent migrations:

```bash
# Run all migration scripts
for f in db/migrate_*.sql; do
  echo "Running $f..."
  docker exec -i pf9_db psql -U pf9 -d pf9_mgmt < "$f"
done
```

---

## Scheduled Tasks (cron)

On Windows, `deployment.ps1` creates two Windows Task Scheduler tasks. On Linux, use cron:

```bash
# Open crontab editor
crontab -e
```

Add these entries:

```cron
# PF9 Metrics Collection — every 30 minutes
*/30 * * * * cd /opt/pf9-mngt && /opt/pf9-mngt/.venv/bin/python host_metrics_collector.py --once >> /opt/pf9-mngt/logs/metrics_cron.log 2>&1

# PF9 RVTools Inventory Sync — daily at 02:00
0 2 * * * cd /opt/pf9-mngt && /opt/pf9-mngt/.venv/bin/python pf9_rvtools.py >> /opt/pf9-mngt/logs/rvtools_cron.log 2>&1
```

> **Note**: Use the full path to the venv Python to ensure the correct interpreter and packages are used.

### Verify Cron is Working

```bash
# Check cron service
sudo systemctl status cron   # Ubuntu/Debian
sudo systemctl status crond  # RHEL/CentOS

# View your cron entries
crontab -l

# Check cron logs
grep CRON /var/log/syslog     # Ubuntu/Debian
grep CRON /var/log/cron       # RHEL/CentOS
```

---

## startup.sh — Linux Startup Script

Here is the bash equivalent of `startup.ps1`:

```bash
#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# ─── Validate .env ───────────────────────────────────────
if [ ! -f .env ]; then
    echo "ERROR: .env file not found. Copy .env.example to .env and configure it."
    exit 1
fi

# Check critical variables
for var in POSTGRES_PASSWORD LDAP_ADMIN_PASSWORD PGADMIN_PASSWORD DEFAULT_ADMIN_PASSWORD; do
    val=$(grep "^${var}=" .env | cut -d'=' -f2-)
    if [ -z "$val" ] || [[ "$val" == *"<"* ]]; then
        echo "ERROR: $var is not set or still a placeholder in .env"
        exit 1
    fi
done

echo "✓ .env validated"

# ─── Ensure directories ─────────────────────────────────
mkdir -p reports logs monitoring/cache

# ─── Collect initial metrics ─────────────────────────────
if [ -f .venv/bin/python ]; then
    echo "Collecting initial metrics..."
    .venv/bin/python host_metrics_collector.py --once || true
fi

# ─── Stop existing services ──────────────────────────────
echo "Stopping existing services..."
docker compose down 2>/dev/null || true

# ─── Start services ──────────────────────────────────────
echo "Starting services..."
docker compose up -d

# ─── Wait for startup ────────────────────────────────────
echo "Waiting 15 seconds for services to initialize..."
sleep 15

# ─── Verify services ─────────────────────────────────────
echo ""
echo "Service Status:"
echo "─────────────────────────────────────"
for svc in pf9_db pf9_api pf9_ui pf9_monitoring pf9_backup_worker; do
    status=$(docker inspect --format='{{.State.Status}}' "$svc" 2>/dev/null || echo "not found")
    if [ "$status" = "running" ]; then
        echo "  ✓ $svc: running"
    else
        echo "  ✗ $svc: $status"
    fi
done

# ─── Install cron job (if not already installed) ─────────
if ! crontab -l 2>/dev/null | grep -q "host_metrics_collector"; then
    echo ""
    echo "Installing metrics collection cron job (every 30 min)..."
    (crontab -l 2>/dev/null; echo "*/30 * * * * cd $PROJECT_DIR && $PROJECT_DIR/.venv/bin/python host_metrics_collector.py --once >> $PROJECT_DIR/logs/metrics_cron.log 2>&1") | crontab -
    echo "✓ Cron job installed"
fi

echo ""
echo "═══════════════════════════════════════════"
echo "  pf9-mngt is running"
echo "═══════════════════════════════════════════"
echo "  UI:         http://localhost:5173"
echo "  API:        http://localhost:8000"
echo "  API Docs:   http://localhost:8000/docs"
echo "  Monitoring: http://localhost:8001"
echo "  pgAdmin:    http://localhost:8080"
echo "═══════════════════════════════════════════"
```

Save this as `startup.sh` in the project root, then:

```bash
chmod +x startup.sh
./startup.sh
```

---

## systemd Service (Optional)

For production deployments, you can create a systemd service so pf9-mngt starts automatically on boot:

```bash
sudo tee /etc/systemd/system/pf9-mngt.service << 'EOF'
[Unit]
Description=Platform9 Management System
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/pf9-mngt
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
User=root

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable pf9-mngt
sudo systemctl start pf9-mngt
```

Check status:

```bash
sudo systemctl status pf9-mngt
```

---

## Differences from Windows Deployment

### Things That Are Identical

- **docker-compose.yml** — no changes.
- **.env file** — same variables, same format.
- **All Docker containers** — same images, same behavior.
- **Database schema and migrations** — identical SQL.
- **API endpoints** — identical behavior.
- **ldap/setup.sh** — already exists and works on Linux natively.

### Things That Are Different

| Area | Windows | Linux |
|------|---------|-------|
| **Deployment wizard** | `deployment.ps1` (interactive PowerShell) | Manual setup (steps above) or `startup.sh` |
| **Startup** | `startup.ps1` | `startup.sh` (above) or `docker compose up -d` |
| **Scheduled metrics** | Task Scheduler (every 30 min) | cron (every 30 min) |
| **Scheduled inventory** | Task Scheduler (daily 2 AM) | cron (daily 2 AM) |
| **Monitoring fix** | `fix_monitoring.ps1` | `python3 host_metrics_collector.py --once` + verify cron |
| **Background processes** | `Start-Process -WindowStyle Hidden` | cron (preferred) or `nohup ... &` |
| **Docker install** | Docker Desktop for Windows | `docker-ce` + `docker-compose-plugin` |
| **Python path** | Auto-detected by PowerShell | Use `.venv/bin/python` explicitly |
| **LDAP setup** | `setup_ldap.ps1` | `ldap/setup.sh` (already exists) |

### Known Considerations

1. **File permissions**: On Linux, ensure the user running Docker has permission to write to bind-mounted directories (`monitoring/cache/`, `logs/`, `reports/`, `backups/`). If you get permission errors:
   ```bash
   sudo chown -R $(id -u):$(id -g) monitoring/cache logs reports backups
   ```

2. **Docker socket**: If you see "permission denied" errors with `docker compose`, ensure your user is in the `docker` group or use `sudo`.

3. **SELinux (RHEL/CentOS)**: If SELinux is enforcing, you may need `:Z` suffix on bind mounts or configure SELinux policies:
   ```bash
   # Quick fix (development only):
   sudo setenforce 0
   
   # Production: use :Z flag in docker-compose volume mounts
   ```

4. **Firewall**: Ensure ports 5173, 8000, 8001, 8080, 8081 are accessible if needed from other machines:
   ```bash
   # Ubuntu (ufw)
   sudo ufw allow 5173/tcp
   sudo ufw allow 8000/tcp
   
   # RHEL (firewalld)
   sudo firewall-cmd --add-port=5173/tcp --permanent
   sudo firewall-cmd --add-port=8000/tcp --permanent
   sudo firewall-cmd --reload
   ```

---

## Quick Start (TL;DR)

```bash
# Clone and enter
git clone https://github.com/erezrozenbaum/pf9-mngt.git
cd pf9-mngt

# Create directories
mkdir -p logs secrets reports monitoring/cache backups

# Set up Python
python3 -m venv .venv
source .venv/bin/activate
pip install requests aiohttp openpyxl psycopg2-binary cryptography python-dotenv

# Configure
cp .env.example .env
nano .env  # Set your passwords, PF9 credentials, host IPs

# Initialize metrics
python3 host_metrics_collector.py --once

# Start everything
docker compose up -d --build

# Initialize LDAP
chmod +x ldap/setup.sh && ./ldap/setup.sh

# Set up cron
(crontab -l 2>/dev/null; echo "*/30 * * * * cd $(pwd) && $(pwd)/.venv/bin/python host_metrics_collector.py --once >> $(pwd)/logs/metrics_cron.log 2>&1") | crontab -
(crontab -l 2>/dev/null; echo "0 2 * * * cd $(pwd) && $(pwd)/.venv/bin/python pf9_rvtools.py >> $(pwd)/logs/rvtools_cron.log 2>&1") | crontab -

# Done — open http://localhost:5173
```

---

## Stopping & Restarting

```bash
# Stop all services
docker compose down

# Restart
docker compose up -d

# View logs
docker compose logs -f pf9_api
docker compose logs -f pf9_monitoring

# Rebuild after code changes
docker compose up -d --build
```

---

## Troubleshooting

### Metrics Not Updating

```bash
# Check if cron is running
crontab -l | grep host_metrics

# Run manually to test
source .venv/bin/activate
python3 host_metrics_collector.py --once

# Check the output file exists and has data
cat monitoring/cache/metrics_cache.json | python3 -m json.tool | head -20
```

### Container Won't Start

```bash
# Check logs
docker compose logs pf9_api
docker compose logs pf9_db

# Check .env is valid
grep -E "^(POSTGRES_PASSWORD|LDAP_ADMIN_PASSWORD|DEFAULT_ADMIN_PASSWORD)=" .env
```

### Database Connection Refused

```bash
# Verify the database is healthy
docker exec pf9_db pg_isready -U pf9

# Check if the port is in use by something else
ss -tlnp | grep 5432
```

### LDAP Authentication Fails

```bash
# Test LDAP connectivity
docker exec pf9_ldap ldapsearch -x -H ldap://localhost -D "cn=admin,dc=pf9mgmt,dc=local" \
  -w "$LDAP_ADMIN_PASSWORD" -b "dc=pf9mgmt,dc=local" "(objectClass=*)" dn

# Re-run LDAP setup if needed
./ldap/setup.sh
```

---

**Document Status**: Ready for Use  
**Last Updated**: February 2026
