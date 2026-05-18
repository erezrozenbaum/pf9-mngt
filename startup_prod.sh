#!/usr/bin/env bash
# startup_prod.sh — PF9 Management Portal Production Startup (Linux/macOS)
# Bash equivalent of startup_prod.ps1
# See startup_prod.ps1 for Windows equivalent.
#
# Starts the stack with docker-compose.prod.yml overlay applied:
#   - Ports 8000, 5173, 8001 are NOT exposed to the host (nginx-only access)
#   - UI is served as a built static bundle via nginx (Dockerfile.prod)
#   - Gunicorn runs 4 workers with request recycling
#   - nginx uses nginx.prod.conf (proxies pf9_ui:80, no Vite HMR)
#
# Usage:
#   ./startup_prod.sh           — start production stack
#   ./startup_prod.sh --stop    — stop all services
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

COMPOSE_CMD="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
STOP_ONLY=false
for arg in "$@"; do
    case "$arg" in
        --stop|-s) STOP_ONLY=true ;;
    esac
done

echo "=== PF9 Management Portal — PRODUCTION ==="

if $STOP_ONLY; then
    echo "Stopping production services..."
    $COMPOSE_CMD down
    echo "Stopped."
    exit 0
fi

# Step 0: Validate .env
echo "0. Validating .env file..."
if [[ ! -f ".env" ]]; then
    echo "ERROR: .env file not found." >&2
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
    exit 1
fi
echo "OK: Environment validated"

# Warn if TENANT_DB_PASSWORD absent
if [[ -z "${ENV_MAP[TENANT_DB_PASSWORD]:-}" ]]; then
    echo "  WARNING: TENANT_DB_PASSWORD not set — ensure secrets/tenant_portal_db_password is populated"
fi

# Step 0b: Check secrets/ files
echo "0b. Checking secrets/ files..."
SECRET_FILES=("secrets/db_password" "secrets/ldap_admin_password" "secrets/pf9_password" "secrets/jwt_secret" "secrets/ldap_sync_key")
EMPTY_SECRETS=()
for f in "${SECRET_FILES[@]}"; do
    if [[ ! -f "$f" ]] || [[ ! -s "$f" ]]; then
        EMPTY_SECRETS+=("$f")
    fi
done
if [[ ${#EMPTY_SECRETS[@]} -gt 0 ]]; then
    echo "  WARNING: The following secret files are empty — falling back to .env values:"
    printf '    %s\n' "${EMPTY_SECRETS[@]}"
    echo "  See: secrets/README.md"
else
    echo "  OK: All secrets/ files populated"
fi

# Step 0c: Ensure required directories
mkdir -p reports

IS_DEMO=false
[[ "${ENV_MAP[DEMO_MODE]:-}" == "true" ]] && IS_DEMO=true

# Step 1: Stop existing services
echo "1. Stopping existing services..."
$COMPOSE_CMD down 2>/dev/null || true

# Step 2: Check backup profile / NFS
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

# Step 3: Pull images then start
echo "3. Pulling pre-built images..."
$COMPOSE_CMD pull 2>/dev/null || echo "  WARNING: Some images could not be pulled — starting with cached versions"

echo "3b. Starting PRODUCTION services..."
$COMPOSE_CMD up -d
echo "OK: Production services started"

# Step 3c: Run database migrations
echo "3c. Running database migrations (alembic upgrade head)..."
# Wait up to 30 s for the DB to accept connections before migrating
DB_READY=false
for _ in $(seq 1 15); do
    if docker exec pf9_db pg_isready -U pf9 -q 2>/dev/null; then
        DB_READY=true
        break
    fi
    sleep 2
done
if ! $DB_READY; then
    echo "  WARNING: DB not ready after 30 s — skipping migration (manual run: docker exec pf9_api alembic -c db/alembic.ini upgrade head)"
else
    docker exec pf9_api alembic -c db/alembic.ini upgrade head
    if [ $? -eq 0 ]; then
        echo "  OK: Migrations applied"
    else
        echo "  ERROR: Migration failed — check logs with: docker logs pf9_api"
        exit 1
    fi
fi

# Step 4: Wait for API health
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

# Step 6: Verify production port isolation
echo ""
echo "6. Verifying production port isolation..."
EXPOSED_PORTS="$(docker ps --format "{{.Ports}}" 2>/dev/null || echo "")"
LEAKED_PORTS=()
for p in 5173 8000 8001; do
    if echo "$EXPOSED_PORTS" | grep -q "0\.0\.0\.0:${p}->"; then
        LEAKED_PORTS+=("$p")
    fi
done
if [[ ${#LEAKED_PORTS[@]} -eq 0 ]]; then
    echo "  OK: Backend ports (5173/8000/8001) not exposed — nginx-only access"
else
    echo "  WARNING: Ports still exposed: ${LEAKED_PORTS[*]}"
    echo "    Check docker-compose.prod.yml is being applied correctly."
fi

# Final status
echo ""
if $ALL_GOOD; then
    echo "=== PRODUCTION STACK READY ==="
    echo ""
    echo "Access:"
    echo "  * https://localhost  <-- only entry point (nginx TLS)"
    echo "  * http://localhost   <-- redirects to https"
    echo ""
    echo "Ports 5173, 8000, 8001 are closed — all traffic goes through nginx."
    echo ""
    if $IS_DEMO; then
        echo "OK: Demo mode — scheduler worker uses static cache"
    else
        echo "OK: Metrics & RVTools inventory run inside pf9_scheduler_worker"
        echo "  Interval: ${ENV_MAP[METRICS_INTERVAL_SECONDS]:-60}s"
        RVTOOLS_INTERVAL="${ENV_MAP[RVTOOLS_INTERVAL_MINUTES]:-}"
        if [[ -n "$RVTOOLS_INTERVAL" ]] && [[ "$RVTOOLS_INTERVAL" -gt 0 ]]; then
            echo "  Inventory: every ${RVTOOLS_INTERVAL} minute(s)"
        else
            echo "  Inventory: daily at ${ENV_MAP[RVTOOLS_SCHEDULE_TIME]:-03:00} UTC"
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
    echo "To stop: ./startup_prod.sh --stop"
    echo "Switch to dev: ./startup.sh"
else
    echo "=== ISSUES DETECTED ==="
    echo "Check logs with: docker compose -f docker-compose.yml -f docker-compose.prod.yml logs <service>"
    exit 1
fi
