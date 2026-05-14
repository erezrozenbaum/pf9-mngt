#!/usr/bin/env bash
# deployment.sh — PF9 Management System Automated Deployment (Linux/macOS)
# Bash equivalent of deployment.ps1
# See deployment.ps1 for Windows equivalent.
#
# Usage:
#   ./deployment.sh                  Full deployment with all checks
#   ./deployment.sh --stop           Stop all services and remove volumes
#   ./deployment.sh --quick-start    Skip Docker installation check
#   ./deployment.sh --no-schedule    Skip cron job setup
#   ./deployment.sh --skip-metrics   Skip initial metrics collection
#   ./deployment.sh --skip-health    Skip health checks
#   ./deployment.sh --force-rebuild  Force Docker image rebuild (no cache)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Parse arguments ────────────────────────────────────────────────────────
STOP=false
QUICK_START=false
NO_SCHEDULE=false
SKIP_METRICS=false
SKIP_HEALTH=false
FORCE_REBUILD=false

for arg in "$@"; do
    case "$arg" in
        --stop)           STOP=true ;;
        --quick-start)    QUICK_START=true ;;
        --no-schedule)    NO_SCHEDULE=true ;;
        --skip-metrics)   SKIP_METRICS=true ;;
        --skip-health)    SKIP_HEALTH=true ;;
        --force-rebuild)  FORCE_REBUILD=true ;;
    esac
done

# ── Helpers ────────────────────────────────────────────────────────────────
section() { echo ""; echo "================================================================"; echo " $*"; echo "================================================================"; }
ok()      { echo "OK:      $*"; }
info()    { echo "INFO:    $*"; }
warn()    { echo "WARNING: $*"; }
err()     { echo "ERROR:   $*" >&2; }

# ── Stop mode ─────────────────────────────────────────────────────────────
if $STOP; then
    section "Stopping PF9 Management System"
    docker compose down -v
    ok "All services stopped and volumes removed"
    exit 0
fi

section "PF9 Management System — Automated Deployment"
info "Starting comprehensive deployment process..."

# ── Step 1: Docker check ──────────────────────────────────────────────────
if ! $QUICK_START; then
    section "Step 1: Checking Docker Installation"
    if ! command -v docker &>/dev/null; then
        err "Docker is not installed."
        info "Install Docker Engine: https://docs.docker.com/engine/install/"
        exit 1
    fi
    ok "Docker is installed"
    if ! docker info &>/dev/null; then
        err "Docker daemon is not running. Start Docker and try again."
        exit 1
    fi
    ok "Docker daemon is running"
    if ! docker compose version &>/dev/null; then
        err "Docker Compose plugin not found. Install Docker Compose v2: https://docs.docker.com/compose/install/"
        exit 1
    fi
    ok "Docker Compose is installed"
else
    section "Step 1: Docker Check (Skipped)"
    info "Quick-start mode — assuming Docker is installed and running"
fi

# ── Step 2: Environment configuration ─────────────────────────────────────
section "Step 2: Environment Configuration"

if [[ ! -f ".env" ]]; then
    if [[ -f ".env.example" ]]; then
        info "Creating .env from .env.example..."
        cp .env.example .env
        ok "Created .env file"
    else
        err ".env.example not found"
        exit 1
    fi

    # Interactive wizard
    section "Environment Configuration Wizard"
    info "Press Enter to accept defaults shown in [brackets]."
    echo ""

    prompt() {
        local msg="$1" default="${2:-}" secret="${3:-false}"
        if $secret; then
            read -r -s -p "$msg: " val; echo ""
        else
            read -r -p "$msg${default:+ [$default]}: " val
        fi
        echo "${val:-$default}"
    }

    set_env() {
        local key="$1" value="$2"
        if grep -q "^${key}=" .env; then
            # Use perl for safe in-place replacement (avoids BSD/GNU sed differences)
            perl -i -pe "s|^${key}=.*|${key}=${value}|" .env
        else
            echo "${key}=${value}" >> .env
        fi
    }

    # Deployment mode
    echo "── Deployment Mode ──"
    MODE="$(prompt "Deployment mode ([1] Production  [2] Demo Mode)" "1")"
    IS_DEMO=false
    if [[ "$MODE" == "2" ]]; then
        IS_DEMO=true
        set_env "DEMO_MODE" "true"
        ok "Demo mode enabled"
    else
        set_env "DEMO_MODE" "false"
    fi
    echo ""

    # Platform9 credentials
    if ! $IS_DEMO; then
        echo "── Platform9 API Credentials ──"
        PF9_AUTH_URL="$(prompt "Platform9 Keystone URL")"
        PF9_USERNAME="$(prompt "Platform9 Username (email)")"
        PF9_PASSWORD="$(prompt "Platform9 Password" "" true)"
        PF9_USER_DOMAIN="$(prompt "Platform9 User Domain" "Default")"
        PF9_PROJECT_NAME="$(prompt "Platform9 Project Name" "service")"
        PF9_REGION_NAME="$(prompt "Platform9 Region Name" "region-one")"
        PF9_REGION_URL="$(prompt "Platform9 Region URL")"
        set_env "PF9_AUTH_URL"     "$PF9_AUTH_URL"
        set_env "PF9_USERNAME"     "$PF9_USERNAME"
        set_env "PF9_PASSWORD"     "$PF9_PASSWORD"
        set_env "PF9_USER_DOMAIN"  "$PF9_USER_DOMAIN"
        set_env "PF9_PROJECT_NAME" "$PF9_PROJECT_NAME"
        set_env "PF9_REGION_NAME"  "$PF9_REGION_NAME"
        set_env "PF9_REGION_URL"   "$PF9_REGION_URL"
        echo ""
    fi

    # Database
    echo "── Database Configuration ──"
    PG_USER="$(prompt "PostgreSQL Username" "pf9")"
    PG_PASSWORD="$(prompt "PostgreSQL Password (min 16 chars)" "" true)"
    PG_DB="$(prompt "PostgreSQL Database Name" "pf9_mgmt")"
    set_env "POSTGRES_USER"     "$PG_USER"
    set_env "POSTGRES_PASSWORD" "$PG_PASSWORD"
    set_env "POSTGRES_DB"       "$PG_DB"
    set_env "PF9_DB_USER"       "$PG_USER"
    set_env "PF9_DB_PASSWORD"   "$PG_PASSWORD"
    set_env "PF9_DB_NAME"       "$PG_DB"
    echo ""

    # pgAdmin
    echo "── pgAdmin ──"
    PGADMIN_EMAIL="$(prompt "pgAdmin email" "admin@pf9-mgmt.local")"
    PGADMIN_PASSWORD="$(prompt "pgAdmin password" "" true)"
    set_env "PGADMIN_EMAIL"    "$PGADMIN_EMAIL"
    set_env "PGADMIN_PASSWORD" "$PGADMIN_PASSWORD"
    echo ""

    # LDAP
    echo "── LDAP Directory Configuration ──"
    LDAP_ORG="$(prompt "LDAP Organization Name" "Platform9 Management")"
    LDAP_DOMAIN="$(prompt "LDAP Domain (e.g. company.com)" "pf9mgmt.local")"
    LDAP_ADMIN_PW="$(prompt "LDAP Admin Password" "" true)"
    LDAP_CONFIG_PW="$(prompt "LDAP Config Password" "" true)"
    LDAP_READONLY_PW="$(prompt "LDAP Readonly User Password" "" true)"
    LDAP_BASE_DN="$(echo "$LDAP_DOMAIN" | tr '.' '\n' | sed 's/^/dc=/' | paste -sd ',' -)"
    set_env "LDAP_ORGANISATION"      "$LDAP_ORG"
    set_env "LDAP_DOMAIN"            "$LDAP_DOMAIN"
    set_env "LDAP_ADMIN_PASSWORD"    "$LDAP_ADMIN_PW"
    set_env "LDAP_CONFIG_PASSWORD"   "$LDAP_CONFIG_PW"
    set_env "LDAP_READONLY_USER"     "true"
    set_env "LDAP_READONLY_PASSWORD" "$LDAP_READONLY_PW"
    set_env "LDAP_BASE_DN"           "$LDAP_BASE_DN"
    set_env "LDAP_USER_DN"           "ou=users,$LDAP_BASE_DN"
    set_env "LDAP_GROUP_DN"          "ou=groups,$LDAP_BASE_DN"
    echo ""

    # Admin user
    echo "── Web Portal Admin ──"
    ADMIN_USER="$(prompt "Admin Username" "admin")"
    ADMIN_PASSWORD="$(prompt "Admin Password" "" true)"
    set_env "DEFAULT_ADMIN_USER"     "$ADMIN_USER"
    set_env "DEFAULT_ADMIN_PASSWORD" "$ADMIN_PASSWORD"
    echo ""

    # JWT secret
    JWT_SECRET="$(LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 64)"
    set_env "JWT_SECRET_KEY" "$JWT_SECRET"
    ok "Generated JWT secret key"

    # LDAP sync encryption key
    mkdir -p secrets
    LDAP_SYNC_KEY="$(dd if=/dev/urandom bs=32 count=1 2>/dev/null | base64 | tr -d '\n=')"
    set_env "LDAP_SYNC_KEY" "$LDAP_SYNC_KEY"
    echo -n "$LDAP_SYNC_KEY" > secrets/ldap_sync_key
    ok "Generated LDAP sync encryption key (secrets/ldap_sync_key)"

    ok "Environment configuration complete!"
    info "Settings saved to .env"
    echo ""
else
    ok ".env file already exists"
    info "To reconfigure, delete .env and run deployment again"
fi

# ── Step 3: Validate .env ─────────────────────────────────────────────────
section "Step 3: Validating Environment Configuration"

declare -A ENV_MAP
while IFS='=' read -r key val; do
    [[ "$key" =~ ^\s*# ]] && continue
    [[ -z "$key" ]] && continue
    ENV_MAP["$key"]="${val:-}"
done < <(grep '=' .env | grep -v '^\s*#')

IS_DEMO="${ENV_MAP[DEMO_MODE]:-false}"
REQUIRED_VARS=("POSTGRES_USER" "POSTGRES_PASSWORD" "POSTGRES_DB" "LDAP_ADMIN_PASSWORD" "DEFAULT_ADMIN_PASSWORD" "PGADMIN_PASSWORD" "JWT_SECRET_KEY")
if [[ "$IS_DEMO" != "true" ]]; then
    REQUIRED_VARS+=("PF9_USERNAME" "PF9_PASSWORD" "PF9_AUTH_URL")
fi

MISSING=()
for v in "${REQUIRED_VARS[@]}"; do
    val="${ENV_MAP[$v]:-}"
    if [[ -z "$val" ]] || [[ "$val" =~ ^\<.*\>$ ]]; then
        MISSING+=("$v")
    fi
done
if [[ ${#MISSING[@]} -gt 0 ]]; then
    err "Missing or empty required environment variables:"
    printf '  - %s\n' "${MISSING[@]}" >&2
    exit 1
fi
ok "All required environment variables are set"

# ── Step 4: Directory structure ───────────────────────────────────────────
section "Step 4: Creating Directory Structure"
for dir in logs secrets reports monitoring/cache pf9-ui/dist; do
    mkdir -p "$dir"
    ok "Exists: $dir"
done

if [[ ! -f metrics_cache.json ]]; then
    echo '{"vms":[],"hosts":[],"alerts":[],"summary":{"total_vms":0,"total_hosts":0,"last_update":null},"timestamp":null}' > metrics_cache.json
    ok "Created metrics cache file"
fi
ok "Directory structure ready"

# ── Step 5: Python environment ────────────────────────────────────────────
section "Step 5: Python Environment Setup"
PYTHON_EXE=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON_EXE="$(command -v "$cmd")"
        break
    fi
done

if [[ -n "$PYTHON_EXE" ]]; then
    ok "Python found: $PYTHON_EXE"
    info "Installing required Python packages..."
    for pkg in requests aiohttp openpyxl psycopg2-binary cryptography; do
        "$PYTHON_EXE" -m pip install --quiet "$pkg" &>/dev/null && ok "Installed: $pkg" || warn "Could not install: $pkg (may already be installed)"
    done
    if ! $SKIP_METRICS && [[ "$IS_DEMO" != "true" ]]; then
        info "Collecting initial metrics snapshot..."
        "$PYTHON_EXE" host_metrics_collector.py --once &>/dev/null && ok "Initial metrics collected" || warn "Metrics collection failed (will retry later)"
    elif [[ "$IS_DEMO" == "true" ]]; then
        info "Demo mode — skipping live metrics collection"
    fi
else
    warn "Python not found — metrics collection will be unavailable"
    info "Install Python 3.11+: https://www.python.org/downloads/"
fi

# ── Step 6: Cron (optional) ───────────────────────────────────────────────
if ! $NO_SCHEDULE && ! $SKIP_METRICS && [[ -n "$PYTHON_EXE" ]]; then
    section "Step 6: Configuring Automated Metrics Collection (cron)"
    # Remove existing entries
    crontab -l 2>/dev/null | grep -v "host_metrics_collector\|pf9_rvtools" | crontab - || true
    CRON_LINES="*/30 * * * * $PYTHON_EXE $SCRIPT_DIR/host_metrics_collector.py --once >> $SCRIPT_DIR/logs/metrics_cron.log 2>&1"$'\n'"0 2 * * * $PYTHON_EXE $SCRIPT_DIR/pf9_rvtools.py >> $SCRIPT_DIR/logs/rvtools_cron.log 2>&1"
    (crontab -l 2>/dev/null; echo "$CRON_LINES") | crontab -
    ok "Cron jobs created (metrics every 30 min, RVTools daily at 02:00)"
else
    section "Step 6: Metrics Collection (Skipped)"
    $NO_SCHEDULE  && info "Scheduled metrics collection disabled (--no-schedule)"
    $SKIP_METRICS && info "Metrics collection skipped (--skip-metrics)"
fi

# ── Step 7: Build and start Docker services ───────────────────────────────
section "Step 7: Building and Starting Docker Services"

if [[ ! -f nginx/certs/server.crt ]] || [[ ! -f nginx/certs/server.key ]]; then
    info "Generating self-signed TLS certificates for nginx..."
    if [[ -f nginx/generate_certs.sh ]]; then
        bash nginx/generate_certs.sh && ok "TLS certificates generated" || warn "Could not generate TLS certs — place server.crt and server.key in nginx/certs/"
    elif command -v openssl &>/dev/null; then
        mkdir -p nginx/certs
        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
            -keyout nginx/certs/server.key \
            -out nginx/certs/server.crt \
            -subj "/C=US/ST=CA/L=SanJose/O=PF9/CN=localhost" &>/dev/null
        ok "Self-signed TLS certificate generated via openssl"
    else
        warn "openssl not found — place server.crt and server.key in nginx/certs/ manually"
    fi
fi

info "Pulling base images..."
docker compose pull 2>/dev/null || warn "Could not pull some images (will build from scratch)"

if $FORCE_REBUILD; then
    info "Force rebuilding all containers..."
    docker compose build --no-cache
    ok "Containers rebuilt"
fi

info "Starting all services..."
docker compose up -d --build
ok "All services started"

info "Waiting for services to initialize..."
sleep 15

# ── Step 8: Database verification ─────────────────────────────────────────
section "Step 8: Verifying Database Schema"
sleep 5
TABLE_COUNT="$(docker exec pf9_db psql -U "${ENV_MAP[POSTGRES_USER]}" -d "${ENV_MAP[POSTGRES_DB]}" -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" 2>/dev/null | tr -d ' \n' || echo 0)"
if [[ "$TABLE_COUNT" -gt 20 ]]; then
    ok "Database initialized with $TABLE_COUNT tables"
else
    warn "Database may not be fully initialized ($TABLE_COUNT tables found) — check: docker compose logs db"
fi

# Run all migrations via run_migration.py (idempotent)
section "Step 8a: Running Database Migrations"
if [[ -n "$PYTHON_EXE" ]] && [[ -f run_migration.py ]]; then
    info "Running all pending migrations via run_migration.py..."
    "$PYTHON_EXE" run_migration.py && ok "All migrations applied" || warn "Migration runner exited with errors — check output above"
else
    warn "run_migration.py not found or Python unavailable — migrations may need manual application"
fi

# ── Step 8b: Ensure admin user ────────────────────────────────────────────
section "Step 8b: Ensuring Admin User and Superadmin Permissions"
ADMIN_USER="${ENV_MAP[DEFAULT_ADMIN_USER]:-admin}"
ADMIN_PASSWORD="${ENV_MAP[DEFAULT_ADMIN_PASSWORD]:-}"
if [[ -z "$ADMIN_PASSWORD" ]]; then
    err "DEFAULT_ADMIN_PASSWORD is not set in .env"
    exit 1
fi

docker exec pf9_db psql -U "${ENV_MAP[POSTGRES_USER]}" -d "${ENV_MAP[POSTGRES_DB]}" -c \
    "INSERT INTO user_roles (username, role, granted_by, granted_at, is_active) VALUES ('$ADMIN_USER', 'superadmin', 'system', now(), true) ON CONFLICT (username) DO UPDATE SET role='superadmin', granted_by='system', granted_at=now(), is_active=true;" &>/dev/null
ok "Admin user ensured in user_roles"

docker exec pf9_db psql -U "${ENV_MAP[POSTGRES_USER]}" -d "${ENV_MAP[POSTGRES_DB]}" -c \
    "INSERT INTO role_permissions (role, resource, action) VALUES ('superadmin', '*', 'admin') ON CONFLICT DO NOTHING;" &>/dev/null
ok "Wildcard permission for superadmin ensured"

# ── Step 9b: Demo data seeding ────────────────────────────────────────────
if [[ "$IS_DEMO" == "true" ]] && [[ -n "$PYTHON_EXE" ]]; then
    section "Step 9b: Seeding Demo Data"
    info "Populating database with sample tenants, VMs, volumes, snapshots..."
    "$PYTHON_EXE" seed_demo_data.py \
        --db-host localhost --db-port 5432 \
        --db-name "${ENV_MAP[POSTGRES_DB]}" \
        --db-user "${ENV_MAP[POSTGRES_USER]}" \
        --db-pass "${ENV_MAP[POSTGRES_PASSWORD]}" \
        && ok "Demo data seeded" || warn "Demo seeding exited with errors — run: python seed_demo_data.py"
fi

# ── Step 10: Health checks ────────────────────────────────────────────────
if ! $SKIP_HEALTH; then
    section "Step 10: Running Health Checks"
    ALL_OK=true

    check_url() {
        local name="$1" url="$2"
        if curl -fsSk --max-time 5 "$url" &>/dev/null; then
            ok "$name is responding"
        else
            warn "$name is not responding ($url)"
            ALL_OK=false
        fi
    }

    check_container() {
        local name="$1" container="$2"
        st="$(docker inspect --format '{{.State.Status}}' "$container" 2>/dev/null || echo "not_found")"
        if [[ "$st" == "running" ]]; then
            ok "$name container is running"
        else
            warn "$name container status: $st"
            ALL_OK=false
        fi
    }

    sleep 5
    check_url "nginx HTTPS"  "https://localhost/health"
    check_url "API"          "http://localhost:8000/health"
    check_url "API Docs"     "http://localhost:8000/docs"
    check_url "Monitoring"   "http://localhost:8001/health"
    check_url "UI"           "http://localhost:5173"
    check_container "Redis" "pf9_redis"
    check_container "Notification Worker" "pf9_notification_worker"
    check_container "Metering Worker"     "pf9_metering_worker"

    echo ""
    if $ALL_OK; then
        ok "All health checks passed"
    else
        warn "Some checks failed — review output above. The portal may still be starting."
    fi
fi

# ── Final summary ─────────────────────────────────────────────────────────
section "Deployment Complete"
echo ""
echo "PF9 Management Portal is ready!"
echo ""
echo "Services:"
echo "  * HTTPS (nginx): https://localhost"
echo "  * UI (direct):   http://localhost:5173"
echo "  * API (direct):  http://localhost:8000"
echo "  * API Metrics:   http://localhost:8000/metrics"
echo "  * Monitoring:    http://localhost:8001"
echo "  * PgAdmin:       http://localhost:8080  (dev profile only)"
echo ""
echo "Management:"
echo "  Start:   ./startup.sh"
echo "  Stop:    ./startup.sh --stop"
echo "  Prod:    ./startup_prod.sh"
echo "  Logs:    docker compose logs <service_name>"
