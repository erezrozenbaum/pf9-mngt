#!/usr/bin/env powershell
# PF9 Management Portal — Production Startup Script
#
# Starts the stack with docker-compose.prod.yml overlay applied:
#   - Ports 8000, 5173, 8001 are NOT exposed to the host (nginx-only access)
#   - UI is served as a built static bundle via nginx (Dockerfile.prod)
#   - Gunicorn runs 4 workers with request recycling
#   - nginx uses nginx.prod.conf (proxies pf9_ui:80, no Vite HMR)
#
# Requires: secrets/ files populated (see secrets/README.md) OR .env fallback
#
# Usage:
#   .\startup_prod.ps1           — start production stack
#   .\startup_prod.ps1 -StopOnly — stop all services

param(
    [switch]$StopOnly
)

Write-Host "=== PF9 Management Portal — PRODUCTION ===" -ForegroundColor Magenta

# Change to script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$COMPOSE_CMD = "docker compose -f docker-compose.yml -f docker-compose.prod.yml"

if ($StopOnly) {
    Write-Host "Stopping production services..." -ForegroundColor Yellow
    # Equivalent to: docker compose -f docker-compose.yml -f docker-compose.prod.yml down
    # Named volumes (pf9_pgdata, pf9_ldap_data, etc.) are NEVER deleted by 'down'.
    # Add -v / --volumes only if you intentionally want to wipe all data.
    Invoke-Expression "$COMPOSE_CMD down"

    @("PF9 Metrics Collection", "PF9 RVTools Export") | ForEach-Object {
        try { schtasks /delete /tn $_ /f 2>$null | Out-Null } catch {}
    }

    Write-Host "Stopped." -ForegroundColor Green
    exit 0
}

# ── Function: remove legacy Windows Scheduled Tasks ────────────────────────
function Remove-LegacyScheduledTasks {
    $legacyTasks = @("PF9 Metrics Collection", "PF9 RVTools Export")
    foreach ($task in $legacyTasks) {
        schtasks /query /tn $task 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            schtasks /delete /tn $task /f | Out-Null
            Write-Host "  ✓ Removed legacy Windows Task: $task" -ForegroundColor Green
        }
    }
}

# ── Step 0: Validate .env ──────────────────────────────────────────────────
Write-Host "0. Validating .env file..." -ForegroundColor Yellow
if (-not (Test-Path ".env")) {
    Write-Host "✗ .env file not found. Run deployment.ps1 first or copy .env.example to .env" -ForegroundColor Red
    exit 1
}

$envContent = Get-Content ".env" | Where-Object { $_ -notmatch '^\s*#' -and $_ -match '=' }
$envCheckMap = @{}
foreach ($line in $envContent) {
    $parts = $line -split '=', 2
    if ($parts.Count -eq 2) { $envCheckMap[$parts[0].Trim()] = $parts[1].Trim() }
}

$criticalVars = @('POSTGRES_PASSWORD', 'LDAP_ADMIN_PASSWORD', 'PGADMIN_PASSWORD', 'DEFAULT_ADMIN_PASSWORD')
$missingVars = @()
foreach ($v in $criticalVars) {
    $val = $envCheckMap[$v]
    if (-not $val -or $val -match '^<.*>$') { $missingVars += $v }
}
if ($missingVars.Count -gt 0) {
    Write-Host "✗ Missing or placeholder values in .env:" -ForegroundColor Red
    foreach ($v in $missingVars) { Write-Host "    - $v" -ForegroundColor Red }
    exit 1
}
Write-Host "✓ Environment validated" -ForegroundColor Green

# ── Step 0b: Warn if secrets/ files are still empty ────────────────────────
Write-Host "0b. Checking secrets/ files..." -ForegroundColor Yellow
$secretFiles = @("secrets/db_password", "secrets/ldap_admin_password", "secrets/pf9_password", "secrets/jwt_secret")
$emptySecrets = @()
foreach ($f in $secretFiles) {
    if (-not (Test-Path $f) -or (Get-Item $f).Length -eq 0) { $emptySecrets += $f }
}
if ($emptySecrets.Count -gt 0) {
    Write-Host "  ⚠ The following secret files are empty — falling back to .env values:" -ForegroundColor Yellow
    foreach ($f in $emptySecrets) { Write-Host "      $f" -ForegroundColor Yellow }
    Write-Host "  (This is fine for now. Populate secrets/ for full Docker Secrets security.)" -ForegroundColor Gray
    Write-Host "  See: secrets/README.md" -ForegroundColor Gray
} else {
    Write-Host "  ✓ All secrets/ files populated" -ForegroundColor Green
}

# ── Step 0c: Ensure required directories ──────────────────────────────────
if (-not (Test-Path ".\reports")) {
    New-Item -ItemType Directory -Force -Path ".\reports" | Out-Null
    Write-Host "✓ Created reports directory" -ForegroundColor Green
}

$isDemoMode = ($envCheckMap['DEMO_MODE'] -eq 'true')

# ── Step 1: Stop existing services ────────────────────────────────────────
Write-Host "1. Stopping existing services..." -ForegroundColor Yellow
Invoke-Expression "$COMPOSE_CMD down" 2>$null | Out-Null

# ── Step 2: Remove legacy Windows Scheduled Tasks ─────────────────────────
Write-Host "2. Checking for legacy Windows Scheduled Tasks..." -ForegroundColor Yellow
Remove-LegacyScheduledTasks

Get-Process | Where-Object {
    $_.ProcessName -match "python" -and
    ($_.CommandLine -like "*host_metrics_collector*" -or $_.CommandLine -like "*pf9_rvtools*")
} | ForEach-Object {
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    Write-Host "  ✓ Stopped legacy background python process (PID $($_.Id))" -ForegroundColor Green
}

# ── Step 3: Pre-flight NFS check ──────────────────────────────────────────
$activeProfiles = ($envCheckMap['COMPOSE_PROFILES'] -split ',') | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' }
$backupEnabled = $activeProfiles -contains 'backup'

if ($backupEnabled) {
    $nfsServer = $envCheckMap['NFS_BACKUP_SERVER']
    Write-Host "3a. Checking NFS connectivity to $nfsServer port 2049..." -ForegroundColor Yellow
    $nfsOk = $false
    if ($nfsServer) {
        try {
            $tcpClient = New-Object System.Net.Sockets.TcpClient
            $connect = $tcpClient.BeginConnect($nfsServer, 2049, $null, $null)
            $waited = $connect.AsyncWaitHandle.WaitOne(3000, $false)
            if ($waited -and $tcpClient.Connected) { $nfsOk = $true }
            $tcpClient.Close()
        } catch {}
    }
    if ($nfsOk) {
        Write-Host "  ✓ NFS server reachable" -ForegroundColor Green
    } else {
        Write-Host "  ✗ NFS server $nfsServer NOT reachable on port 2049" -ForegroundColor Red
        $choice = Read-Host "  Start WITHOUT backup worker for now? (Y/n)"
        if ($choice -eq '' -or $choice -match '^[Yy]') {
            $env:COMPOSE_PROFILES = ($activeProfiles | Where-Object { $_ -ne 'backup' }) -join ','
            Write-Host "  → Starting without backup profile." -ForegroundColor Cyan
        } else {
            Write-Host "  Aborting." -ForegroundColor Red
            exit 1
        }
    }
}

# ── Step 4: Start production stack ────────────────────────────────────────
$staleVol = docker volume ls --quiet --filter "name=pf9-mngt_nfs_backups" 2>$null
if ($staleVol) { docker volume rm pf9-mngt_nfs_backups 2>$null | Out-Null }

Write-Host "3. Building and starting PRODUCTION services..." -ForegroundColor Yellow
Write-Host "   (This may take a few minutes on first run — UI is compiled into static assets)" -ForegroundColor Gray

try {
    Invoke-Expression "$COMPOSE_CMD up -d --build"
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ All services started" -ForegroundColor Green
    } else {
        Write-Host "✗ Failed to start services" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "✗ Docker compose failed" -ForegroundColor Red
    exit 1
}

# ── Step 5: Wait for services ─────────────────────────────────────────────
Write-Host "4. Waiting for services to be ready..." -ForegroundColor Yellow
Start-Sleep 20   # Prod UI build + nginx needs a bit more time to initialize

# ── Step 6: Verify services ───────────────────────────────────────────────
Write-Host "5. Verifying services..." -ForegroundColor Yellow

$services = @(
    @{Name="Database";          Container="pf9_db"},
    @{Name="API";               Container="pf9_api"},
    @{Name="UI";                Container="pf9_ui"},
    @{Name="Monitoring";        Container="pf9_monitoring"},
    @{Name="Scheduler Worker";  Container="pf9_scheduler_worker"},
    @{Name="Redis";             Container="pf9_redis"},
    @{Name="nginx";             Container="pf9_nginx"}
)

$allGood = $true
foreach ($service in $services) {
    $status = docker ps --filter "name=$($service.Container)" --format "{{.Status}}"
    if ($status -like "*Up*") {
        Write-Host "  ✓ $($service.Name) is running" -ForegroundColor Green
    } else {
        Write-Host "  ✗ $($service.Name) is NOT running" -ForegroundColor Red
        $allGood = $false
    }
}

# ── Step 7: Confirm ports are closed ──────────────────────────────────────
Write-Host ""
Write-Host "6. Verifying production port isolation..." -ForegroundColor Yellow
$exposedRaw = docker ps --format "{{.Ports}}" 2>$null
$leakedPorts = @()
foreach ($p in @("5173", "8000", "8001")) {
    if ($exposedRaw -match "0\.0\.0\.0:$p->") { $leakedPorts += $p }
}
if ($leakedPorts.Count -eq 0) {
    Write-Host "  ✓ Backend ports (5173/8000/8001) not exposed — nginx-only access" -ForegroundColor Green
} else {
    Write-Host "  ⚠ Ports still exposed: $($leakedPorts -join ', ')" -ForegroundColor Yellow
    Write-Host "    Check docker-compose.prod.yml is being applied correctly." -ForegroundColor Gray
}

# ── Final status ──────────────────────────────────────────────────────────
Write-Host ""
if ($allGood) {
    Write-Host "=== PRODUCTION STACK READY ===" -ForegroundColor Magenta
    Write-Host ""
    Write-Host "Access:" -ForegroundColor Cyan
    Write-Host "  • https://localhost  ← only entry point (nginx TLS)" -ForegroundColor Green
    Write-Host "  • http://localhost   ← redirects to https" -ForegroundColor White
    Write-Host ""
    Write-Host "Ports 5173, 8000, 8001 are closed — all traffic goes through nginx." -ForegroundColor Gray
    Write-Host ""

    if ($isDemoMode) {
        Write-Host "✓ Demo mode — scheduler worker uses static cache" -ForegroundColor Green
    } else {
        Write-Host "✓ Metrics & RVTools inventory run inside pf9_scheduler_worker" -ForegroundColor Green
        Write-Host "  Interval : $($envCheckMap['METRICS_INTERVAL_SECONDS'] ?? '60') s" -ForegroundColor Gray
        $rvInterval = $envCheckMap['RVTOOLS_INTERVAL_MINUTES']
        if ($rvInterval -and [int]$rvInterval -gt 0) {
            Write-Host "  Inventory: every $rvInterval minute(s)" -ForegroundColor Gray
        } else {
            Write-Host "  Inventory: daily at $($envCheckMap['RVTOOLS_SCHEDULE_TIME'] ?? '03:00') UTC" -ForegroundColor Gray
        }
    }

    if ($backupEnabled) {
        $bwStatus = docker ps --filter "name=pf9_backup_worker" --format "{{.Status}}"
        if ($bwStatus -like "*Up*") {
            Write-Host "✓ Backup worker running — NFS backups active" -ForegroundColor Green
        } else {
            Write-Host "✗ Backup worker not running — check NFS_BACKUP_SERVER in .env" -ForegroundColor Red
        }
    } else {
        Write-Host "  Backups: disabled (set COMPOSE_PROFILES=backup in .env to enable)" -ForegroundColor Gray
    }

    Write-Host ""
    Write-Host "To stop: .\startup_prod.ps1 -StopOnly" -ForegroundColor Cyan
    Write-Host "Switch to dev: .\startup.ps1" -ForegroundColor Cyan
} else {
    Write-Host "=== ISSUES DETECTED ===" -ForegroundColor Red
    Write-Host "Check logs with: docker compose -f docker-compose.yml -f docker-compose.prod.yml logs <service>" -ForegroundColor Yellow
    exit 1
}
