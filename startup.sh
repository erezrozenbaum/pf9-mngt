#!/usr/bin/env bash
# startup.sh — PF9 Management Portal Startup Script (Linux/macOS)
# Bash equivalent of startup.ps1
# See startup.ps1 for Windows equivalent.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

STOP_ONLY=false
for arg in "$@"; do
    case "$arg" in
        --stop|-s) STOP_ONLY=true ;;
    esac
done

echo "=== PF9 Management Portal Setup ==="

if $STOP_ONLY; then
    echo "Stopping services and cleaning up..."
    docker compose down
    echo "Cleanup completed"
    exit 0
fi

# Step 0: Validate .env
echo "0. Validating .env file..."
if [[ ! -f ".env" ]]; then
    echo "ERROR: .env file not found. Run deployment.sh first or copy .env.example to .env" >&2
    exit 1
fi

declare -A ENV_MAP
while IFS='=' read -r key val; do
    [[ "$key" =~ ^\s*# ]] && continue
    [[ -z "$key" ]] && continue
    ENV_MAP["$key"]="${val:-}"
done < <(grep '=' .env | grep -v '^\s*#')

CRITICAL_VARS=("POSTGRES_PASSWORD" "LDAP_ADMIN_PASSWORD" "PGADMIN_PASSWORD" "DEFAULT_ADMIN_PASSWORD")
MISSING_VARS=()
for v in "${CRITICAL_VARS[@]}"; do
    val="${ENV_MAP[$v]:-}"
    if [[ -z "$val" ]] || [[ "$val" =~ ^\<.*\>$ ]]; then
        MISSING_VARS+=("$v")
    fi
done
if [[ ${#MISSING_VARS[@]} -gt 0 ]]; then
    echo "ERROR: Missing or placeholder values in .env:" >&2
    printf '  - %s\n' "${MISSING_VARS[@]}" >&2
    echo "  Please run deployment.sh or edit .env before starting." >&2
    exit 1
fi

# Warn if TENANT_DB_PASSWORD absent
if [[ -z "${ENV_MAP[TENANT_DB_PASSWORD]:-}" ]]; then
    echo "  WARNING: TENANT_DB_PASSWORD not set (tenant portal DB connections will fail)"
fi

# Ensure reports directory exists
mkdir -p reports
echo "OK: Environment validated"

# Detect demo mode
IS_DEMO=false
[[ "${ENV_MAP[DEMO_MODE]:-}" == "true" ]] && IS_DEMO=true

# Step 1: Stop existing services
echo "1. Stopping existing services..."
docker compose down 2>/dev/null || true

# Step 2: Check for backup profile
ACTIVE_PROFILES="${ENV_MAP[COMPOSE_PROFILES]:-}"
BACKUP_ENABLED=false
[[ "$ACTIVE_PROFILES" == *"backup"* ]] && BACKUP_ENABLED=true

if $BACKUP_ENABLED; then
    NFS_SERVER="${ENV_MAP[NFS_BACKUP_SERVER]:-}"
    echo "3a. Checking NFS connectivity to $NFS_SERVER port 2049..."
    if timeout 3 bash -c ">/dev/tcp/$NFS_SERVER/2049" 2>/dev/null; then
        echo "  OK: NFS server reachable"
    else
        echo "  ERROR: NFS server $NFS_SERVER NOT reachable on port 2049"
        read -r -p "  Start WITHOUT backup worker for now? (Y/n) " choice
        choice="${choice:-Y}"
        if [[ "$choice" =~ ^[Yy]$ ]]; then
            ACTIVE_PROFILES="${ACTIVE_PROFILES//backup/}"
            ACTIVE_PROFILES="${ACTIVE_PROFILES//,,/,}"
            ACTIVE_PROFILES="${ACTIVE_PROFILES#,}"
            ACTIVE_PROFILES="${ACTIVE_PROFILES%,}"
            export COMPOSE_PROFILES="$ACTIVE_PROFILES"
            echo "  Starting without backup profile."
        else
            echo "  Aborting."
            exit 1
        fi
    fi
fi

# Remove stale NFS volume if present
if docker volume ls --quiet --filter "name=pf9-mngt_nfs_backups" 2>/dev/null | grep -q .; then
    docker volume rm pf9-mngt_nfs_backups 2>/dev/null || true
fi

# Step 3: Build and start
echo "3. Building and starting Docker services..."
docker compose up -d --build
echo "OK: All services started"

# Step 4: Wait for services
echo "4. Waiting for services to be ready..."
ELAPSED=0
MAX_WAIT=90
READY=false
printf "   Polling API health "
while [[ $ELAPSED -lt $MAX_WAIT ]]; do
    if docker exec pf9_api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" 2>/dev/null; then
        READY=true
        break
    fi
    printf "."
    sleep 2
    ELAPSED=$((ELAPSED + 2))
done
echo ""
if $READY; then
    echo "   OK: API is healthy (${ELAPSED}s)"
else
    echo "   WARNING: API not yet responding after ${MAX_WAIT}s — continuing anyway"
fi

# Step 5: Verify services
echo "5. Verifying services..."
declare -A SERVICES=(
    [Database]=pf9_db
    [API]=pf9_api
    [UI]=pf9_ui
    [Monitoring]=pf9_monitoring
    [Scheduler_Worker]=pf9_scheduler_worker
    [Intelligence_Worker]=pf9_intelligence_worker
    [Redis]=pf9_redis
    [nginx]=pf9_nginx
)

ALL_GOOD=true
for name in "${!SERVICES[@]}"; do
    container="${SERVICES[$name]}"
    st="$(docker ps --filter "name=${container}" --format "{{.Status}}" 2>/dev/null || echo "")"
    if [[ "$st" == *"Up"* ]]; then
        echo "  OK: ${name} is running"
    else
        echo "  ERROR: ${name} is NOT running"
        ALL_GOOD=false
    fi
done

echo ""
if $ALL_GOOD; then
    echo "=== SUCCESS ==="
    echo "PF9 Management Portal is ready!"
    echo ""
    echo "Services:"
    echo "  * HTTPS (nginx): https://localhost"
    echo "  * UI (direct):   http://localhost:5173"
    echo "  * API (direct):  http://localhost:8000"
    echo "  * API Metrics:   http://localhost:8000/metrics"
    echo "  * Monitoring:    http://localhost:8001"
    echo ""
    if $IS_DEMO; then
        echo "OK: Demo mode — scheduler worker uses static cache"
    else
        echo "OK: Metrics collection & RVTools inventory run inside pf9_scheduler_worker"
        METRICS_INTERVAL="${ENV_MAP[METRICS_INTERVAL_SECONDS]:-60}"
        echo "  Interval: ${METRICS_INTERVAL}s"
        RVTOOLS_INTERVAL="${ENV_MAP[RVTOOLS_INTERVAL_MINUTES]:-}"
        if [[ -n "$RVTOOLS_INTERVAL" ]] && [[ "$RVTOOLS_INTERVAL" -gt 0 ]]; then
            echo "  Inventory: every ${RVTOOLS_INTERVAL} minute(s)"
        else
            SCHEDULE_TIME="${ENV_MAP[RVTOOLS_SCHEDULE_TIME]:-03:00}"
            echo "  Inventory: daily at ${SCHEDULE_TIME} UTC"
        fi
    fi
    if $BACKUP_ENABLED; then
        bw_st="$(docker ps --filter "name=pf9_backup_worker" --format "{{.Status}}" 2>/dev/null || echo "")"
        if [[ "$bw_st" == *"Up"* ]]; then
            echo "OK: Backup worker running — NFS backups active"
        else
            echo "ERROR: Backup worker not running — check NFS_BACKUP_SERVER in .env"
        fi
    else
        echo "  Backups: disabled (set COMPOSE_PROFILES=backup in .env to enable)"
    fi
    echo ""
    echo "To stop: ./startup.sh --stop"
else
    echo "=== ISSUES DETECTED ==="
    echo "Some services may not be running correctly."
    echo "Check logs with: docker compose logs <service_name>"
    exit 1
fi
