#!/usr/bin/env powershell
<#
.SYNOPSIS
  Complete automated deployment for PF9 Management System (Windows).
  
.DESCRIPTION
  Fully automated deployment that:
  - Installs Docker Desktop if not present
  - Creates .env from template with guided configuration
  - Sets up all directories and prerequisites
  - Builds all Docker containers
  - Initializes LDAP and PostgreSQL with schemas
  - Configures automated metrics collection
  - Runs comprehensive health checks
  
  The only manual step required is updating .env with your credentials.

.EXAMPLE
  .\deployment.ps1
  Full deployment with all checks and initialization
  
.EXAMPLE
  .\deployment.ps1 -Stop
  Stop all services and clean up
  
.EXAMPLE
  .\deployment.ps1 -QuickStart
  Skip Docker installation check (assumes Docker is already installed)
#>

param(
    [switch]$Stop,
    [switch]$QuickStart,
    [switch]$NoSchedule,
    [switch]$SkipMetrics,
    [switch]$SkipHealthCheck,
    [switch]$ForceRebuild
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-Section($message) {
    Write-Host ""
    Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host " $message" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
}

function Write-Success($message) {
    Write-Host "✓ $message" -ForegroundColor Green
}

function Write-Info($message) {
    Write-Host "→ $message" -ForegroundColor White
}

function Write-Warning($message) {
    Write-Host "⚠ $message" -ForegroundColor Yellow
}

function Write-Error($message) {
    Write-Host "✗ $message" -ForegroundColor Red
}

function Test-AdminPrivileges {
    $currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Install-DockerDesktop {
    Write-Section "Installing Docker Desktop for Windows"
    
    if (-not (Test-AdminPrivileges)) {
        Write-Error "Administrator privileges required to install Docker Desktop."
        Write-Info "Please run this script as Administrator or install Docker Desktop manually:"
        Write-Info "https://www.docker.com/products/docker-desktop"
        throw "Admin privileges required"
    }
    
    $downloadUrl = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
    $installerPath = "$env:TEMP\DockerDesktopInstaller.exe"
    
    Write-Info "Downloading Docker Desktop installer..."
    try {
        Invoke-WebRequest -Uri $downloadUrl -OutFile $installerPath -UseBasicParsing
        Write-Success "Downloaded Docker Desktop installer"
    } catch {
        Write-Error "Failed to download Docker Desktop installer"
        Write-Info "Please download manually from: https://www.docker.com/products/docker-desktop"
        throw "Download failed"
    }
    
    Write-Info "Installing Docker Desktop (this may take several minutes)..."
    Start-Process -FilePath $installerPath -ArgumentList "install", "--quiet", "--accept-license" -Wait -NoNewWindow
    
    Remove-Item $installerPath -Force
    
    Write-Success "Docker Desktop installed successfully"
    Write-Warning "Please restart your computer and run this script again."
    Write-Warning "After restart, you may need to enable virtualization in BIOS if prompted."
    exit 0
}

function Test-Http($url, $timeoutSec = 5) {
    try {
        $response = Invoke-WebRequest -Uri $url -Method Get -TimeoutSec $timeoutSec -UseBasicParsing -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

function Invoke-Compose($arguments) {
    & docker-compose $arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "docker-compose command failed"
    }
}

$ScriptDir = $PSScriptRoot

# Handle --Stop mode
if ($Stop) {
    Write-Section "Stopping PF9 Management System"
    Set-Location $ScriptDir
    Invoke-Compose @("down", "-v")
    Write-Success "All services stopped and volumes removed"
    exit 0
}

Write-Section "PF9 Management System - Automated Deployment"
Write-Info "Starting comprehensive deployment process..."

# Step 1: Docker Environment Check
if (-not $QuickStart) {
    Write-Section "Step 1: Checking Docker Installation"
    
    $dockerInstalled = Get-Command docker -ErrorAction SilentlyContinue
    $composeInstalled = Get-Command docker-compose -ErrorAction SilentlyContinue
    
    if (-not $dockerInstalled) {
        Write-Warning "Docker is not installed"
        $install = Read-Host "Would you like to install Docker Desktop now? (y/n)"
        if ($install -eq 'y' -or $install -eq 'Y') {
            Install-DockerDesktop
        } else {
            Write-Error "Docker is required for deployment"
            Write-Info "Download Docker Desktop from: https://www.docker.com/products/docker-desktop"
            exit 1
        }
    }
    
    Write-Success "Docker is installed"
    
    if (-not $composeInstalled) {
        Write-Error "Docker Compose is not installed"
        Write-Info "Please install Docker Desktop which includes Docker Compose"
        exit 1
    }
    
    Write-Success "Docker Compose is installed"
    
    # Verify Docker daemon is running
    try {
        docker info 2>&1 | Out-Null
        Write-Success "Docker daemon is running"
    } catch {
        Write-Error "Docker daemon is not running"
        Write-Info "Please start Docker Desktop and try again"
        exit 1
    }
} else {
    Write-Section "Step 1: Docker Check (Skipped)"
    Write-Info "QuickStart mode - assuming Docker is installed and running"
}

# Step 2: Environment Configuration
Write-Section "Step 2: Environment Configuration"

Set-Location $ScriptDir

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Write-Info "Creating .env from .env.example..."
        Copy-Item ".env.example" ".env"
        Write-Success "Created .env file"
        Write-Warning "Please update .env with your Platform9 credentials:"
        Write-Info "  - PF9_USERNAME: Your Platform9 username"
        Write-Info "  - PF9_PASSWORD: Your Platform9 password"
        Write-Info "  - PF9_REGION: Your Platform9 region URL"
        Write-Info ""
        $continue = Read-Host "Have you updated the .env file with your credentials? (y/n)"
        if ($continue -ne 'y' -and $continue -ne 'Y') {
            Write-Warning "Deployment paused. Please update .env and run the script again."
            exit 0
        }
    } else {
        Write-Error ".env.example not found"
        Write-Info "Please ensure .env.example exists in the project root"
        exit 1
    }
} else {
    Write-Success ".env file already exists"
}

# Step 3: Validate Environment File
Write-Section "Step 3: Validating Environment Configuration"

$envContent = Get-Content ".env" | Where-Object { $_ -notmatch '^\s*#' -and $_ -match '=' }
$envMap = @{}

foreach ($line in $envContent) {
    $parts = $line -split '=', 2
    if ($parts.Count -eq 2) {
        $key = $parts[0].Trim()
        $value = $parts[1].Trim()
        $envMap[$key] = $value
    }
}

$requiredVars = @(
    'PF9_USERNAME',
    'PF9_PASSWORD',
    'PF9_REGION',
    'POSTGRES_USER',
    'POSTGRES_PASSWORD',
    'POSTGRES_DB'
)

$missing = @()
foreach ($var in $requiredVars) {
    if (-not $envMap.ContainsKey($var) -or [string]::IsNullOrWhiteSpace($envMap[$var])) {
        $missing += $var
    }
}

if ($missing.Count -gt 0) {
    Write-Error "Missing or empty required environment variables:"
    foreach ($var in $missing) {
        Write-Host "  - $var" -ForegroundColor Red
    }
    Write-Info "Please update .env with all required values"
    exit 1
}

Write-Success "All required environment variables are set"

# Step 4: Prepare Directory Structure
Write-Section "Step 4: Creating Directory Structure"

$directories = @(
    ".\logs",
    ".\secrets",
    ".\api\__pycache__",
    ".\monitoring\cache",
    ".\pf9-ui\dist"
)

foreach ($dir in $directories) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        Write-Success "Created: $dir"
    } else {
        Write-Info "Exists: $dir"
    }
}

# Ensure metrics cache exists
if (-not (Test-Path ".\metrics_cache.json")) {
    @{
        vms = @()
        hosts = @()
        alerts = @()
        summary = @{
            total_vms = 0
            total_hosts = 0
            last_update = $null
        }
        timestamp = $null
    } | ConvertTo-Json | Set-Content ".\metrics_cache.json"
    Write-Success "Created metrics cache file"
}

Write-Success "Directory structure ready"

# Step 5: Python Environment Setup
Write-Section "Step 5: Python Environment Setup"

$pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonExe) {
    $pythonExe = (Get-Command python3 -ErrorAction SilentlyContinue).Source
}

if ($pythonExe) {
    Write-Success "Python found: $pythonExe"
    
    Write-Info "Installing required Python packages..."
    $requiredPackages = @('requests', 'aiohttp', 'openpyxl', 'psycopg2-binary')
    
    foreach ($pkg in $requiredPackages) {
        try {
            & $pythonExe -m pip install --quiet $pkg 2>&1 | Out-Null
            Write-Success "Installed: $pkg"
        } catch {
            Write-Warning "Could not install: $pkg (may already be installed)"
        }
    }
    
    # Collect initial metrics if not skipped
    if (-not $SkipMetrics) {
        Write-Info "Collecting initial metrics snapshot..."
        try {
            & $pythonExe "host_metrics_collector.py" "--once" 2>&1 | Out-Null
            Write-Success "Initial metrics collected"
        } catch {
            Write-Warning "Metrics collection failed (will retry later)"
        }
    }
} else {
    Write-Warning "Python not found - metrics collection will be unavailable"
    Write-Info "Install Python 3.11+ from: https://www.python.org/downloads/"
}

# Step 6: Configure Automated Metrics Collection
if (-not $NoSchedule -and -not $SkipMetrics -and $pythonExe) {
    Write-Section "Step 6: Configuring Automated Metrics Collection"
    
    Write-Info "Removing existing scheduled tasks (if any)..."
    try {
        schtasks /delete /tn "PF9 Metrics Collection" /f 2>&1 | Out-Null
    } catch { }
    try {
        schtasks /delete /tn "PF9 RVTools Export" /f 2>&1 | Out-Null
    } catch { }

    Write-Info "Creating metrics collection task (every 30 minutes)..."
    $start = (Get-Date).AddMinutes(1).ToString("HH:mm")
    $metricsCmd = "cmd /c \"\"$pythonExe\" \"$ScriptDir\host_metrics_collector.py\" --once\""
    
    try {
        schtasks /create /tn "PF9 Metrics Collection" /sc minute /mo 30 /st $start /tr $metricsCmd /ru $env:USERNAME /f 2>&1 | Out-Null
        Write-Success "Metrics collection task created (every 30 minutes)"
    } catch {
        Write-Warning "Could not create metrics task (may need admin privileges)"
        Write-Info "Run manually with: python host_metrics_collector.py"
    }
    
    Write-Info "Creating RVTools export task (daily at 2 AM)..."
    $rvtoolsCmd = "cmd /c \"\"$pythonExe\" \"$ScriptDir\pf9_rvtools.py\"\""
    
    try {
        schtasks /create /tn "PF9 RVTools Export" /sc daily /st 02:00 /tr $rvtoolsCmd /ru $env:USERNAME /f 2>&1 | Out-Null
        Write-Success "RVTools export task created (daily at 2:00 AM)"
    } catch {
        Write-Warning "Could not create RVTools task (may need admin privileges)"
        Write-Info "Run manually with: python pf9_rvtools.py"
    }
} else {
    Write-Section "Step 6: Metrics Collection (Skipped)"
    if ($NoSchedule) {
        Write-Info "Scheduled metrics collection disabled (--NoSchedule)"
    } elseif ($SkipMetrics) {
        Write-Info "Metrics collection skipped (--SkipMetrics)"
    } else {
        Write-Info "Python not available for metrics collection"
    }
}

# Step 7: Build and Start Docker Services
Write-Section "Step 7: Building and Starting Docker Services"

Write-Info "Pulling base images (this may take a few minutes on first run)..."
try {
    Invoke-Compose @("pull") 2>&1 | Out-Null
    Write-Success "Base images pulled"
} catch {
    Write-Warning "Could not pull some images (will build from scratch)"
}

if ($ForceRebuild) {
    Write-Info "Force rebuilding all containers..."
    Invoke-Compose @("build", "--no-cache")
    Write-Success "Containers rebuilt"
}

Write-Info "Starting all services..."
Invoke-Compose @("up", "-d", "--build")
Write-Success "All services started"

Write-Info "Waiting for services to initialize..."
Start-Sleep -Seconds 15

# Step 8: Verify Database Initialization
Write-Section "Step 8: Verifying Database Schema"

Write-Info "Checking database tables..."
Start-Sleep -Seconds 5

try {
    $tableCheck = & docker-compose exec -T db psql -U $envMap['POSTGRES_USER'] -d $envMap['POSTGRES_DB'] -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" 2>&1
    $tableCount = [int]($tableCheck -replace '\s','')
    
    if ($tableCount -gt 20) {
        Write-Success "Database initialized with $tableCount tables"
    } else {
        Write-Warning "Database may not be fully initialized ($tableCount tables found)"
        Write-Info "Check logs with: docker-compose logs db"
    }
} catch {
    Write-Warning "Could not verify database initialization"
    Write-Info "Database may still be starting up - check with: docker-compose logs db"
}

# Step 9: Verify LDAP Initialization
Write-Section "Step 9: Verifying LDAP Directory"

try {
    $ldapCheck = & docker-compose exec -T ldap ldapsearch -x -H ldap://localhost -b "dc=platform9,dc=local" -D "cn=admin,dc=platform9,dc=local" -w $envMap['LDAP_ADMIN_PASSWORD'] "(objectClass=organizationalUnit)" dn 2>&1
    
    if ($ldapCheck -match "numEntries") {
        Write-Success "LDAP directory initialized successfully"
    } else {
        Write-Warning "LDAP directory may not be fully initialized"
        Write-Info "Check logs with: docker-compose logs ldap"
    }
} catch {
    Write-Warning "Could not verify LDAP initialization"
    Write-Info "LDAP may still be starting up - check with: docker-compose logs ldap"
}

# Step 10: Health Checks
if (-not $SkipHealthCheck) {
    Write-Section "Step 10: Running Health Checks"
    
    $checks = @(
        @{Name="API"; Url="http://localhost:8000/health"; Critical=$true},
        @{Name="API Docs"; Url="http://localhost:8000/docs"; Critical=$false},
        @{Name="Monitoring"; Url="http://localhost:8001/health"; Critical=$true},
        @{Name="UI"; Url="http://localhost:5173"; Critical=$true},
        @{Name="pgAdmin"; Url="http://localhost:8080"; Critical=$false}
    )

    $allOk = $true
    $criticalFailed = $false
    
    foreach ($check in $checks) {
        Write-Info "Testing $($check.Name)..."
        Start-Sleep -Seconds 2
        
        if (Test-Http $check.Url) {
            Write-Success "$($check.Name) is responding"
        } else {
            if ($check.Critical) {
                Write-Error "$($check.Name) is not responding (critical)"
                $criticalFailed = $true
            } else {
                Write-Warning "$($check.Name) is not responding (non-critical)"
            }
            $allOk = $false
        }
    }

    if ($criticalFailed) {
        Write-Warning "Some critical services are not responding yet"
        Write-Info "Services may need more time to start. Check status with:"
        Write-Info "  docker-compose ps"
        Write-Info "  docker-compose logs"
    } elseif (-not $allOk) {
        Write-Success "All critical services are running (some optional services pending)"
    } else {
        Write-Success "All services are healthy and responding"
    }
} else {
    Write-Section "Step 10: Health Checks (Skipped)"
    Write-Info "Use --SkipHealthCheck=false to enable health checks"
}

# Final Summary
Write-Section "Deployment Complete!"

Write-Host ""
Write-Host "Access Points:" -ForegroundColor Cyan
Write-Host "  UI:            http://localhost:5173" -ForegroundColor White
Write-Host "  API:           http://localhost:8000" -ForegroundColor White
Write-Host "  API Docs:      http://localhost:8000/docs" -ForegroundColor White
Write-Host "  Monitoring:    http://localhost:8001" -ForegroundColor White
Write-Host "  pgAdmin:       http://localhost:8080" -ForegroundColor White
Write-Host ""

Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "  1. Open UI at http://localhost:5173" -ForegroundColor White
Write-Host "     Default view: Landing Dashboard (🏠) with real-time analytics" -ForegroundColor Gray
Write-Host "  2. Log in with LDAP credentials (admin@platform9.local / changeme)" -ForegroundColor White
Write-Host "  3. Review system health on Landing Dashboard (auto-refreshes every 30s)" -ForegroundColor White
Write-Host "  4. Configure snapshot policies via Snapshots tab" -ForegroundColor White
Write-Host "     Monitor compliance on Dashboard > Snapshot SLA Compliance card" -ForegroundColor White
Write-Host "  5. Review system logs in Audit tab for operations monitoring" -ForegroundColor White
Write-Host "  6. Review security practices in docs/SECURITY_CHECKLIST.md before production" -ForegroundColor White
Write-Host ""

Write-Host "Management Commands:" -ForegroundColor Cyan
Write-Host "  View logs:        docker-compose logs -f" -ForegroundColor White
Write-Host "  Check status:     docker-compose ps" -ForegroundColor White
Write-Host "  Stop services:    docker-compose down" -ForegroundColor White
Write-Host "  Restart service:  docker-compose restart <service>" -ForegroundColor White
Write-Host ""

if ($pythonExe -and -not $SkipMetrics) {
    Write-Host "Automated Tasks:" -ForegroundColor Cyan
    Write-Host "  Metrics Collection:    Every 30 minutes (PF9 Metrics Collection)" -ForegroundColor White
    Write-Host "  RVTools Export:        Daily at 2:00 AM (PF9 RVTools Export)" -ForegroundColor White
    Write-Host "  Compliance Report:     Daily via snapshot_worker container" -ForegroundColor White
    Write-Host ""
    Write-Host "Manual Execution:" -ForegroundColor Cyan
    Write-Host "  Metrics:               python host_metrics_collector.py" -ForegroundColor White
    Write-Host "  RVTools:               python pf9_rvtools.py" -ForegroundColor White
    Write-Host "  Compliance Report:     docker exec pf9_snapshot_worker python snapshots/p9_snapshot_compliance_report.py --sla-days 2" -ForegroundColor White
    Write-Host ""
}

Write-Success "System is ready for use!"
