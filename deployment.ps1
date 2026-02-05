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
    Write-Info "After restart, Docker Desktop will start automatically."
    
    Read-Host "Press Enter to exit"
    exit 0
}

function Test-DockerInstallation {
    $dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $dockerCmd) {
        return $false
    }
    
    try {
        & docker info 2>&1 | Out-Null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Wait-DockerReady {
    Write-Info "Waiting for Docker to be ready..."
    $maxRetries = 30
    $retryCount = 0
    
    while ($retryCount -lt $maxRetries) {
        try {
            & docker info 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Success "Docker is ready"
                return $true
            }
        } catch { }
        
        $retryCount++
        Start-Sleep -Seconds 2
    }
    
    Write-Error "Docker did not become ready in time"
    Write-Info "Please ensure Docker Desktop is running and try again"
    return $false
}

function Get-ComposeCommand {
    if (Get-Command docker-compose -ErrorAction SilentlyContinue) {
        return @("docker-compose")
    }

    if (Get-Command docker -ErrorAction SilentlyContinue) {
        try {
            & docker compose version | Out-Null
            if ($LASTEXITCODE -eq 0) {
                return @("docker", "compose")
            }
        } catch {
            # fall through
        }
    }

    throw "Docker Compose not found. Install Docker Desktop or docker-compose."
}

function Invoke-Compose {
    param([string[]]$Args)
    if ($script:ComposeCmd.Count -eq 1) {
        & $script:ComposeCmd[0] @Args
    } else {
        & $script:ComposeCmd[0] $script:ComposeCmd[1] @Args
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose command failed: $($Args -join ' ')"
    }
}

function Read-DotEnv($path) {
    $map = @{}
    Get-Content $path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $idx = $line.IndexOf("=")
        if ($idx -lt 1) { return }
        $key = $line.Substring(0, $idx).Trim()
        $value = $line.Substring($idx + 1).Trim()
        $map[$key] = $value
    }
    return $map
}

function New-SecurePassword($length = 32) {
    $bytes = New-Object byte[] $length
    $rng = [System.Security.Cryptography.RNGCryptoServiceProvider]::new()
    $rng.GetBytes($bytes)
    $rng.Dispose()
    return [Convert]::ToBase64String($bytes).Substring(0, $length)
}

function Initialize-EnvFile {
    Write-Section "Creating .env configuration file"
    
    if (Test-Path ".\.env") {
        Write-Warning ".env file already exists"
        $overwrite = Read-Host "Do you want to create a new one? (y/N)"
        if ($overwrite -ne "y" -and $overwrite -ne "Y") {
            Write-Info "Using existing .env file"
            return
        }
Write-Host ""
Write-Host "╔═══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║                                                               ║" -ForegroundColor Cyan
Write-Host "║         Platform9 Management System - Deployment             ║" -ForegroundColor Cyan
Write-Host "║              Automated Installation Script                    ║" -ForegroundColor Cyan
Write-Host "║               and Cleaning Up Services"
    
    $script:ComposeCmd = Get-ComposeCommand
    
    Write-Info "Stopping Docker containers..."
    Invoke-Compose @("down", "-v")
    Write-Success "Docker containers stopped"
    
    Write-Info "Removing scheduled task..."
    try { 
        schtasks /delete /tn "PF9 Metrics Collection" /f 2>&1 | Out-Null
        Write-Success "Scheduled task removed"
    } catch { 
        Write-Info "No scheduled task to remove"
    }
    
    Write-Info "Stopping background metrics collectors..."
    Get-Process | Where-Object { $_.ProcessName -match "python" -and $_.CommandLine -like "*host_metrics_collector*" } | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Success "Background processes stopped"
    
    Write-Success "Cleanup complete"
    }
    
    Write-Info "Generating secure passwords and secrets..."
    
    $postgresPassword = New-SecurePassword
    $jwtSecret = New-SecurePassword 64
    $ldapAdminPassword = New-SecurePassword 16
    $ldapConfigPassword = New-SecurePassword 16
    $ldapReadonlyPassword = New-SecurePassword 16
    $defaultAdminPassword = New-SecurePassword 16
    
    # Read template
    $envContent = Get-Content ".\.env.template" -Raw
    
    # Replace passwords with generated values
    $envContent = $envContent -replace 'POSTGRES_PASSWORD=.*', "POSTGRES_PASSWORD=$postgresPassword"
    $envContent = $envContent -replace 'JWT_SECRET_KEY=.*', "JWT_SECRET_KEY=$jwtSecret"
    $envContent = $envContent -replace 'LDAP_ADMIN_PASSWORD=.*', "LDAP_ADMIN_PASSWORD=$ldapAdminPassword"
    $envContent = $envContent -replace 'LDAP_CONFIG_PASSWORD=.*', "LDAP_CONFIG_PASSWORD=$ldapConfigPassword"
    $envContent = $envContent -replace 'LDAP_READONLY_PASSWORD=.*', "LDAP_READONLY_PASSWORD=$ldapReadonlyPassword"
    $envContent = $envContent -replace 'DEFAULT_ADMIN_PASSWORD=.*', "DEFAULT_ADMIN_PASSWORD=$defaultAdminPassword"
    
    # Save to .env
    $envContent | Set-Content ".\.env" -NoNewline
    
    Write-Success ".env file created with secure random passwords"
    Write-Warning "IMPORTANT: You must edit .env and configure:"
    Write-Info "  - PF9_AUTH_URL (your Platform9 cluster URL)"
    Write-Info "  - PF9_USERNAME (your service account)"
    Write-Info "  - PF9_PASSWORD (your service account password)"
    Write-Info "  - PF9_HOSTS (comma-separated list of host IPs for monitoring)"
    Write-Info ""
    Write-Info "Opening .env in notepad for editing..."
    Start-Sleep -Seconds 2
    
    & notepad.exe ".\.env"
    
    Write-Info ""
    $ready = Read-Host "Have you updated .env with your Platform9 credentials? (y/N)"
    if ($ready -ne "y" -and $ready -ne "Y") {
        Write-Warning "Please update .env and run deployment.ps1 again"
        exit 1
    }
}

function Test-Http($url, $retries = 10, $delaySec = 3) {
    for ($i = 0; $i -lt $retries; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri $url -TimeoutSec 5 -UseBasicParsing
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
                return $true
            }
        } catch {
            Start-Sleep -Seconds $delaySec
        }
# Step 1: Check Docker Installation
if (-not $QuickStart) {
    Write-Section "Step 1: Checking Docker Installation"
    
    if (-not (Test-DockerInstallation)) {
        Write-Warning "Docker Desktop not found or not running"
        Write-Info "Docker Desktop is required for this deployment"
        Write-Info ""
        
        $install = Read-Host "Would you like to install Docker Desktop now? (y/N)"
        if ($install -eq "y" -or $install -eq "Y") {
            Install-DockerDesktop
        } else {
            Write-Error "Docker Desktop is required. Please install it manually:"
            Write-Info "https://www.docker.com/products/docker-desktop"
            exit 1
        }
    } else {
        Write-Success "Docker Desktop found"
    }
# Step 3: Validate .env Configuration
Write-Section "Step 3: Validating Configuration"

$envMap = Read-DotEnv ".\.env"
$required = @(
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "JWT_SECRET_KEY",
    "LDAP_ADMIN_PASSWORD",
    "LDAP_CONFIG_PASSWORD",
    "LDAP_READONLY_PASSWORD",
    "PF9_AUTH_URL",
    "PF9_USERNAME",
    "PF9_PASSWORD"
)

$missing = @()
$placeholders = @()

foreach ($key in $required) {
    if (-not $envMap.ContainsKey($key) -or [string]::IsNullOrWhiteSpace($envMap[$key])) {
        $missing += $key
    } elseif ($envMap[$key] -match "change|your|placeholder|example|FIXME") {
        $placeholders += $key
    }
}

if ($missing.Count -gt 0) {
# Step 4: Prepare Directory Structure
Write-Section "Step 4: Creating Directory Structure"

# Step 5: Python and Metrics Setup
Write-Section "Step 5: Python Environment Setup"

$pythonExe = $null
$pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonExe) {
    $pythonExe = (Get-Command python3 -ErrorAction SilentlyContinue).Source
}

if ($pythonExe) {
    Write-Success "Python found: $pythonExe"
    
    # Check/Install required packages
    Write-Info "Checking Python dependencies..."
    $requiredPackages = @("requests", "aiohttp", "openpyxl", "psycopg2-binary")
    
    foreach ($pkg in $requiredPackages) {
        try {
# Step 6: Configure Automated Metrics Collection
if (-not $NoSchedule -and -not $SkipMetrics -and $pythonExe) {
    Write-Section "Step 6: Configuring Automated Metrics Collection"
    
    Write-Info "Removing existing scheduled task (if any)..."
    try {
        schtasks /delete /tn "PF9 Metrics Collection" /f 2>&1 | Out-Null
    } catch { }

    Write-Info "Creating scheduled task for 30-minute intervals..."
    $start = (Get-Date).AddMinutes(1).ToString("HH:mm")
    $taskCmd = "cmd /c \"\"$pythonExe\" \"$ScriptDir\host_metrics_collector.py\" --once\""
    
    try {
        schtasks /create /tn "PF9 Metrics Collection" /sc minute /mo 30 /st $start /tr $taskCmd /ru $env:USERNAME /f 2>&1 | Out-Null
        Write-Success "Scheduled task created successfully"
        Write-Info "Metrics will be collected every 30 minutes"
    } catch {
        Write-Warning "Could not create scheduled task (may need admin privileges)"
        Write-Info "Metrics collection can be run manually with: python host_metrics_collector.py"
    }
} else {
    Write-Section "Step 6: Metrics Collection (Skipped)"
    if ($NoSchedule) {
        Write-Info "Scheduled metrics collection disabled (--NoSchedule)"
    } elseif ($SkipMetrics) {
        Write-Info "Metrics collection skipped (--SkipMetrics)"
    } else {
        Write-Info "Python not available for metrics collection"
            Write-Success "Initial metrics collected"
        } catch {
            Write-Warning "Metrics collection failed (will retry later)"
        }
    }
} else {
    Write-Warning "Python not found - metrics collection will be unavailable"
    Write-Info "Install Python 3.11+ from: https://www.python.org/downloads/"
# Step 7: Build and Start Docker Services
Write-Section "Step 7: Building and Starting Docker Services"

Write-Info "Pulling base images (this may take a few minutes on first run)..."
try {
    Invoke-Compose @("pull") 2>&1 | Out-Null
    Write-Success "Base images pulled"
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
    }
} catch {
    Write-Warning "Could not verify database initialization"
}

# Step 9: Verify LDAP Initialization
Write-Section "Step 9: Verifying LDAP Directory"

Write-Info "Checking LDAP structure..."
Start-Sleep -Seconds 3

try {
    $ldapCheck = & docker-compose exec -T ldap ldapsearch -x -H ldap://localhost -b "dc=$($envMap['LDAP_DOMAIN'].Split('.')[0]),dc=$($envMap['LDAP_DOMAIN'].Split('.')[1])" -LLL 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Success "LDAP directory initialized"
    } else {
        Write-Warning "LDAP directory may need configuration"
    }
} catch {
    Write-Warning "Could not verify LDAP initialization"
}

# Step 10: Health Checks
if (-not $SkipHealthCheck) {
    Write-Section "Step 10: Running Service Health Checks"
    
    $checks = @(
        @{Name="Database"; Container="pf9_db"; Port=5432},
        @{Name="LDAP"; Container="pf9_ldap"; Port=389},
        @{Name="API"; Container="pf9_api"; Url="http://localhost:8000/health"},
        @{Name="Monitoring"; Container="pf9_monitoring"; Url="http://localhost:8001/health"},
        @{Name="UI"; Container="pf9_ui"; Url="http://localhost:5173"}
    )🎉 Deployment Complete!"

Write-Host ""
Write-Host "╔═══════════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║                                                               ║" -ForegroundColor Green
Write-Host "║     Platform9 Management System Successfully Deployed!       ║" -ForegroundColor Green
Write-Host "║                                                               ║" -ForegroundColor Green
Write-Host "╚═══════════════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""

Write-Host "Access your services:" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Main Dashboard:  " -NoNewline; Write-Host "http://localhost:5173" -ForegroundColor Yellow
Write-Host "  API Backend:     " -NoNewline; Write-Host "http://localhost:8000" -ForegroundColor Yellow
Write-Host "  API Docs:        " -NoNewline; Write-Host "http://localhost:8000/docs" -ForegroundColor Yellow
Write-Host "  Monitoring:      " -NoNewline; Write-Host "http://localhost:8001" -ForegroundColor Yellow
Write-Host "  Database Admin:  " -NoNewline; Write-Host "http://localhost:8080" -ForegroundColor Yellow
Write-Host "  LDAP Admin:      " -NoNewline; Write-Host "http://localhost:8081" -ForegroundColor Yellow
Write-Host ""

Write-Host "Default Admin Credentials:" -ForegroundColor Cyan
Write-Host "  Username: " -NoNewline; Write-Host "admin" -ForegroundColor White
Write-Host "  Password: " -NoNewline; Write-Host "$($envMap['DEFAULT_ADMIN_PASSWORD'])" -ForegroundColor White
Write-Host "  (Change this in LDAP Admin after first login)" -ForegroundColor Yellow
Write-Host ""

Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "  1. Open http://localhost:5173 in your browser" -ForegroundColor White
Write-Host "  2. Login with the admin credentials above" -ForegroundColor White
Write-Host "  3. Navigate to Admin → User Management to create additional users" -ForegroundColor White
Write-Host "  4. Check the Monitoring tab to verify Platform9 connectivity" -ForegroundColor White
Write-Host ""

Write-Host "Useful Commands:" -ForegroundColor Cyan
Write-Host "  Stop services:    " -NoNewline; Write-Host ".\deployment.ps1 -Stop" -ForegroundColor White
Write-Host "  View logs:        " -NoNewline; Write-Host "docker-compose logs -f <service>" -ForegroundColor White
Write-Host "  Restart service:  " -NoNewline; Write-Host "docker-compose restart <service>" -ForegroundColor White
Write-Host "  Check status:     " -NoNewline; Write-Host "docker-compose ps" -ForegroundColor White
Write-Host ""

Write-Host "Documentation:" -ForegroundColor Cyan
Write-Host "  Admin Guide:      " -NoNewline; Write-Host "docs\ADMIN_GUIDE.md" -ForegroundColor White
Write-Host "  Quick Reference:  " -NoNewline; Write-Host "docs\QUICK_REFERENCE.md" -ForegroundColor White
Write-Host "  Deployment Guide: " -NoNewline; Write-Host "docs\DEPLOYMENT_GUIDE.md" -ForegroundColor White
Write-Host ""

if ($pythonExe) {
    Write-Host "Metrics collection configured to run every 30 minutes" -ForegroundColor Green
} else {
    Write-Host "Note: Install Python 3.11+ to enable automated metrics collection" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""ner)" --format "{{.Status}}" 2>&1
        
        if ($containerStatus -like "*Up*") {
            # If has URL, test HTTP
            if ($check.Url) {
                if (Test-Http $check.Url -retries 5 -delaySec 2) {
                    Write-Success "$($check.Name) - Healthy"
                } else {
                    Write-Warning "$($check.Name) - Container running but HTTP not responding"
                    $allOk = $false
                }
            } else {
                Write-Success "$($check.Name) - Running"
            }
        } else {
            Write-Error "$($check.Name) - Not running"
            $allOk = $false
        }
    }

    if (-not $allOk) {
        Write-Warning "Some services may need more time to initialize"
        Write-Info "Check status with: docker-compose ps"
        Write-Info "View logs with: docker-compose logs <service-name>"
    }
} else {
    Write-Section "Step 10: Health Checks (Skipped)"
    Write-Info "Health checks skipped (--SkipHealthCheck)"-Info "Waiting for services to initialize..."
Start-Sleep -Seconds 15       hosts = @()
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
    throw "Configuration incomplete"
}

if ($placeholders.Count -gt 0) {
    Write-Warning "Placeholder values detected in .env:"
    $placeholders | ForEach-Object { Write-Info "  - $_" }
    Write-Info ""
    $continue = Read-Host "Continue anyway? (y/N)"
    if ($continue -ne "y" -and $continue -ne "Y") {
        Write-Info "Please update .env and run deployment.ps1 again"
        exit 1
    }
}

Write-Success "Configuration validated"
Write-Info "  Database: $($envMap['POSTGRES_DB'])"
Write-Info "  LDAP Domain: $($envMap['LDAP_DOMAIN'])"
Write-Info "  Platform9: $($envMap['PF9_AUTH_URL'])"

Write-Section "Checking prerequisites"
& docker info | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Docker is not running. Start Docker Desktop and retry."
}

if ($InitEnv -and -not (Test-Path ".\.env")) {
    if (Test-Path ".\.env.template") {
        Copy-Item ".\.env.template" ".\.env"
        Write-Host "Created .env from .env.template. Update required values before deploying." -ForegroundColor Yellow
        exit 1
    } else {
        throw ".env.template not found. Create .env manually."
    }
}

if (-not (Test-Path ".\.env")) {
    throw ".env not found. Create it from .env.template or run deployment.ps1 -InitEnv."
}

Write-Section "Validating .env"
$envMap = Read-DotEnv ".\.env"
$required = @(
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "JWT_SECRET_KEY",
    "LDAP_ADMIN_PASSWORD",
    "LDAP_CONFIG_PASSWORD",
    "LDAP_READONLY_PASSWORD",
    "PF9_AUTH_URL",
    "PF9_USERNAME",
    "PF9_PASSWORD"
)
$missing = @()
foreach ($key in $required) {
    if (-not $envMap.ContainsKey($key) -or [string]::IsNullOrWhiteSpace($envMap[$key])) {
        $missing += $key
    }
}
if ($missing.Count -gt 0) {
    throw "Missing required .env values: $($missing -join ', ')"
}

Write-Section "Preparing directories"
New-Item -ItemType Directory -Force -Path ".\logs" | Out-Null

if (-not $SkipMetrics) {
    Write-Section "Collecting initial metrics"
    $pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $pythonExe) {
        $pythonExe = (Get-Command python3 -ErrorAction SilentlyContinue).Source
    }

    if ($pythonExe) {
        try {
            & $pythonExe "host_metrics_collector.py" "--once" | Out-Null
        } catch {
            Write-Host "Metrics collection failed (non-fatal)." -ForegroundColor Yellow
        }
    } else {
        Write-Host "Python not found. Skipping metrics collection." -ForegroundColor Yellow
    }
}

if (-not $NoSchedule -and -not $SkipMetrics) {
    Write-Section "Configuring scheduled metrics collection"
    try {
        schtasks /delete /tn "PF9 Metrics Collection" /f | Out-Null
    } catch { }

    $pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $pythonExe) {
        $pythonExe = (Get-Command python3 -ErrorAction SilentlyContinue).Source
    }

    if ($pythonExe) {
        $start = (Get-Date).AddMinutes(1).ToString("HH:mm")
        $taskCmd = "cmd /c \"\"$pythonExe\" \"$ScriptDir\host_metrics_collector.py\" --once\""
        schtasks /create /tn "PF9 Metrics Collection" /sc minute /mo 30 /st $start /tr $taskCmd /ru $env:USERNAME /f | Out-Null
        Write-Host "Scheduled task created: PF9 Metrics Collection" -ForegroundColor Green
    } else {
        Write-Host "Python not found. Skipping scheduled task." -ForegroundColor Yellow
    }
}

Write-Section "Starting services"
if ($NoBuild) {
    Invoke-Compose @("up", "-d")
} else {
    Invoke-Compose @("up", "-d", "--build")
}

if (-not $SkipHealthCheck) {
    Write-Section "Running health checks"
    $checks = @(
        @{Name="API"; Url="http://localhost:8000/health"},
        @{Name="Monitoring"; Url="http://localhost:8001/health"},
        @{Name="UI"; Url="http://localhost:5173"}
    )

    $allOk = $true
    foreach ($check in $checks) {
        if (Test-Http $check.Url) {
            Write-Host "✓ $($check.Name) OK" -ForegroundColor Green
        } else {
            Write-Host "✗ $($check.Name) not ready" -ForegroundColor Red
            $allOk = $false
        }
    }

    if (-not $allOk) {
        Write-Host "Some services are not ready yet. Re-check with docker-compose ps." -ForegroundColor Yellow
    }
}

Write-Section "Deployment complete"
Write-Host "UI:         http://localhost:5173" -ForegroundColor White
Write-Host "API:        http://localhost:8000" -ForegroundColor White
Write-Host "API Docs:   http://localhost:8000/docs" -ForegroundColor White
Write-Host "Monitoring: http://localhost:8001" -ForegroundColor White
Write-Host "pgAdmin:    http://localhost:8080" -ForegroundColor White
