#!/usr/bin/env powershell
# PF9 Management Portal Complete Startup Script
# This script sets up automatic metrics collection and starts all services

param(
    [switch]$StopOnly
)

Write-Host "=== PF9 Management Portal Setup ===" -ForegroundColor Cyan

# Change to script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

if ($StopOnly) {
    Write-Host "Stopping services and cleaning up..." -ForegroundColor Yellow

    # Stop Docker services (COMPOSE_PROFILES in .env is read automatically by docker compose)
    docker compose down
    
    # Remove legacy scheduled tasks if they still exist from a previous setup
    @("PF9 Metrics Collection", "PF9 RVTools Export") | ForEach-Object {
        try {
            schtasks /delete /tn $_ /f 2>$null | Out-Null
            Write-Host "Removed legacy scheduled task: $_" -ForegroundColor Green
        } catch {}
    }
    
    # Stop any lingering background python collectors (legacy)
    Get-Process | Where-Object {$_.ProcessName -eq "python" -and $_.CommandLine -like "*host_metrics_collector*"} | Stop-Process -Force 2>$null
    
    Write-Host "Cleanup completed" -ForegroundColor Green
    exit 0
}

# Function to remove legacy Windows Scheduled Tasks (no longer needed)
function Remove-LegacyScheduledTasks {
    $legacyTasks = @("PF9 Metrics Collection", "PF9 RVTools Export")
    foreach ($task in $legacyTasks) {
        $exists = schtasks /query /tn $task 2>$null
        if ($LASTEXITCODE -eq 0) {
            schtasks /delete /tn $task /f | Out-Null
            Write-Host "  ✓ Removed legacy Windows Task: $task" -ForegroundColor Green
            Write-Host "    (Now handled by pf9_scheduler_worker container)" -ForegroundColor Gray
        }
    }
}

# Step 0: Validate environment file
Write-Host "0. Validating .env file..." -ForegroundColor Yellow
if (-not (Test-Path ".env")) {
    Write-Host "✗ .env file not found. Run deployment.ps1 first or copy .env.example to .env" -ForegroundColor Red
    exit 1
}

$envContent = Get-Content ".env" | Where-Object { $_ -notmatch '^\s*#' -and $_ -match '=' }
$envCheckMap = @{}
foreach ($line in $envContent) {
    $parts = $line -split '=', 2
    if ($parts.Count -eq 2) {
        $envCheckMap[$parts[0].Trim()] = $parts[1].Trim()
    }
}

$criticalVars = @('POSTGRES_PASSWORD', 'LDAP_ADMIN_PASSWORD', 'PGADMIN_PASSWORD', 'DEFAULT_ADMIN_PASSWORD')
$missingVars = @()
foreach ($v in $criticalVars) {
    $val = $envCheckMap[$v]
    if (-not $val -or $val -match '^<.*>$') {
        $missingVars += $v
    }
}
if ($missingVars.Count -gt 0) {
    Write-Host "✗ The following required variables are missing or still have placeholder values in .env:" -ForegroundColor Red
    foreach ($v in $missingVars) { Write-Host "    - $v" -ForegroundColor Red }
    Write-Host "  Please run deployment.ps1 or edit .env before starting." -ForegroundColor Yellow
    exit 1
}

# Warn (do not fail) if TENANT_DB_PASSWORD is absent — the tenant_portal
# service will still start but its DB auth will fail at login time.
$tenantDbPwd = $envCheckMap['TENANT_DB_PASSWORD']
if (-not $tenantDbPwd -or $tenantDbPwd -match '^<.*>$') {
    Write-Host "  ⚠ TENANT_DB_PASSWORD not set in .env (tenant portal DB connections will fail unless secrets/tenant_portal_db_password is populated)" -ForegroundColor Yellow
}

# Ensure reports directory exists for volume mount
if (-not (Test-Path ".\reports")) {
    New-Item -ItemType Directory -Force -Path ".\reports" | Out-Null
    Write-Host "✓ Created reports directory" -ForegroundColor Green
}

Write-Host "✓ Environment validated" -ForegroundColor Green

# Detect demo mode from .env
$isDemoMode = ($envCheckMap['DEMO_MODE'] -eq 'true')

# Step 1: Stop any running services
Write-Host "1. Stopping existing services..." -ForegroundColor Yellow
docker compose down 2>$null | Out-Null

# Step 2: Remove legacy Windows Scheduled Tasks (metrics + rvtools now run inside Docker)
Write-Host "2. Checking for legacy Windows Scheduled Tasks..." -ForegroundColor Yellow
Remove-LegacyScheduledTasks

# Also stop any lingering background python collectors from previous setup
Get-Process | Where-Object {
    $_.ProcessName -match "python" -and
    ($_.CommandLine -like "*host_metrics_collector*" -or $_.CommandLine -like "*pf9_rvtools*")
} | ForEach-Object {
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    Write-Host "  ✓ Stopped legacy background python process (PID $($_.Id))" -ForegroundColor Green
}

# Step 4: Pre-flight NFS check (only when backup profile is active)
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
            if ($waited -and $tcpClient.Connected) {
                $nfsOk = $true
            }
            $tcpClient.Close()
        } catch {}
    }

    if ($nfsOk) {
        Write-Host "  ✓ NFS server reachable — backup worker will start with NFS volume" -ForegroundColor Green
    } else {
        Write-Host "  ✗ NFS server $nfsServer is NOT reachable on port 2049" -ForegroundColor Red
        Write-Host "  ! If you start with COMPOSE_PROFILES=backup the entire stack will fail." -ForegroundColor Yellow
        Write-Host ""
        $choice = Read-Host "  Start WITHOUT backup worker for now? (Y/n)"
        if ($choice -eq '' -or $choice -match '^[Yy]') {
            Write-Host "  → Starting without backup profile. Fix NFS connectivity then restart." -ForegroundColor Cyan
            $env:COMPOSE_PROFILES = ($activeProfiles | Where-Object { $_ -ne 'backup' }) -join ','
        } else {
            Write-Host "  Aborting. Fix NFS connectivity and try again." -ForegroundColor Red
            exit 1
        }
    }
}

# Step 5: Start Docker services
# Remove stale NFS volume so Docker Compose never prompts interactively about config mismatch
# Safe to remove — it's NFS-backed; no local data lives here
$staleVol = docker volume ls --quiet --filter "name=pf9-mngt_nfs_backups" 2>$null
if ($staleVol) {
    docker volume rm pf9-mngt_nfs_backups 2>$null | Out-Null
}

# Production note: to run with production overrides (closed ports, prod nginx config):
#   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
# Populate secrets/ files before using production mode — see secrets/README.md

Write-Host "3. Building and starting Docker services..." -ForegroundColor Yellow
try {
    docker compose up -d --build
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ All services started successfully" -ForegroundColor Green
    } else {
        Write-Host "✗ Failed to start Docker services" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "✗ Docker compose failed" -ForegroundColor Red
    exit 1
}

# Step 5: Wait for services to be ready
Write-Host "4. Waiting for services to be ready..." -ForegroundColor Yellow
Start-Sleep 15

# Step 6: Verify services
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
        Write-Host "✓ $($service.Name) is running" -ForegroundColor Green
    } else {
        Write-Host "✗ $($service.Name) is not running" -ForegroundColor Red
        $allGood = $false
    }
}

# Final status
Write-Host ""
if ($allGood) {
    Write-Host "=== SUCCESS ===" -ForegroundColor Green
    Write-Host "PF9 Management Portal is ready!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Services:" -ForegroundColor Cyan
    Write-Host "  • HTTPS (nginx): https://localhost" -ForegroundColor Green
    Write-Host "  • UI (direct):   http://localhost:5173" -ForegroundColor White
    Write-Host "  • API (direct):  http://localhost:8000" -ForegroundColor White  
    Write-Host "  • API Metrics:   http://localhost:8000/metrics" -ForegroundColor White
    Write-Host "  • Monitoring:    http://localhost:8001" -ForegroundColor White
    Write-Host "  • PgAdmin:       http://localhost:8080  (dev profile only)" -ForegroundColor Gray
    Write-Host ""
    
    # Metrics / RVTools are now handled inside pf9_scheduler_worker container
    if ($isDemoMode) {
        Write-Host "✓ Demo mode — scheduler worker uses static cache" -ForegroundColor Green
    } else {
        Write-Host "✓ Metrics collection & RVTools inventory run inside pf9_scheduler_worker" -ForegroundColor Green
        Write-Host "  Interval : $($envCheckMap['METRICS_INTERVAL_SECONDS'] ?? '60') s" -ForegroundColor Gray
        $rvInterval = $envCheckMap['RVTOOLS_INTERVAL_MINUTES']
        if ($rvInterval -and [int]$rvInterval -gt 0) {
            Write-Host "  Inventory: every $rvInterval minute(s) (RVTOOLS_INTERVAL_MINUTES)" -ForegroundColor Gray
        } else {
            Write-Host "  Inventory: daily at $($envCheckMap['RVTOOLS_SCHEDULE_TIME'] ?? '03:00') UTC (RVTOOLS_SCHEDULE_TIME)" -ForegroundColor Gray
        }
    }
    # Backup worker status (only shown when backup profile is active)
    if ($backupEnabled) {
        $bwStatus = docker ps --filter "name=pf9_backup_worker" --format "{{.Status}}"
        if ($bwStatus -like "*Up*") {
            Write-Host "✓ Backup worker running — NFS backups active" -ForegroundColor Green
        } else {
            Write-Host "✗ Backup worker not running — check NFS_BACKUP_SERVER/NFS_BACKUP_DEVICE in .env" -ForegroundColor Red
        }
    } else {
        Write-Host "  Backups: disabled (set COMPOSE_PROFILES=backup in .env to enable)" -ForegroundColor Gray
    }
    Write-Host ""
    Write-Host "To stop: .\startup.ps1 -StopOnly" -ForegroundColor Cyan
} else {
    Write-Host "=== ISSUES DETECTED ===" -ForegroundColor Red
    Write-Host "Some services may not be running correctly." -ForegroundColor Red
    Write-Host "Check logs with: docker compose logs <service_name>" -ForegroundColor Yellow
    exit 1
}