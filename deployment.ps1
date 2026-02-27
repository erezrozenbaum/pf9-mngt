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
    } else {
        Write-Error ".env.example not found"
        Write-Info "Please ensure .env.example exists in the project root"
        exit 1
    }
    
    # --- Interactive Configuration Wizard ---
    Write-Section "Environment Configuration Wizard"
    Write-Info "We'll now configure your deployment. Press Enter to accept defaults shown in [brackets]."
    Write-Host ""

    function Prompt-Value($prompt, $default, $secret = $false) {
        $displayDefault = if ($default -and -not $secret) { " [$default]" } else { "" }
        if ($secret) {
            $input = Read-Host "$prompt$displayDefault (input hidden)" -AsSecureString
            $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($input)
            $plaintext = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
            if ([string]::IsNullOrWhiteSpace($plaintext) -and $default) { return $default }
            return $plaintext
        } else {
            $input = Read-Host "$prompt$displayDefault"
            if ([string]::IsNullOrWhiteSpace($input) -and $default) { return $default }
            return $input
        }
    }

    function Set-EnvValue($key, $value) {
        $envPath = ".env"
        $content = Get-Content $envPath -Raw
        $escaped = [regex]::Escape($key)
        if ($content -match "(?m)^$escaped=.*$") {
            $content = $content -replace "(?m)^$escaped=.*$", "$key=$value"
        } else {
            $content += "`n$key=$value"
        }
        Set-Content $envPath -Value $content -NoNewline
    }

    # --- Deployment Mode ---
    Write-Host "── Deployment Mode ──" -ForegroundColor Yellow
    Write-Info "Choose how you want to deploy the portal:"
    Write-Host "  [1] Production  - Connect to a live Platform9 environment" -ForegroundColor White
    Write-Host "  [2] Demo Mode   - Pre-populated sample data, no Platform9 required" -ForegroundColor White
    $modeChoice = Prompt-Value "Deployment mode" "1"
    $isDemo = ($modeChoice -eq "2")
    if ($isDemo) {
        Set-EnvValue "DEMO_MODE" "true"
        Write-Success "Demo mode enabled – Platform9 credentials will be skipped"
        Write-Info "The database will be seeded with sample tenants, VMs, volumes, and snapshots."
    } else {
        Set-EnvValue "DEMO_MODE" "false"
    }
    Write-Host ""

    # --- Platform9 Credentials ---
    if (-not $isDemo) {
    Write-Host "── Platform9 API Credentials ──" -ForegroundColor Yellow
    $pf9AuthUrl = Prompt-Value "Platform9 Keystone URL (e.g. https://your-cluster.platform9.com/keystone/v3)" ""
    $pf9Username = Prompt-Value "Platform9 Username (email)" ""
    $pf9Password = Prompt-Value "Platform9 Password" "" $true
    $pf9UserDomain = Prompt-Value "Platform9 User Domain" "Default"
    $pf9ProjectName = Prompt-Value "Platform9 Project Name" "service"
    $pf9RegionName = Prompt-Value "Platform9 Region Name" "region-one"
    $pf9RegionUrl = Prompt-Value "Platform9 Region URL (e.g. https://your-cluster.platform9.com)" ""

    Set-EnvValue "PF9_AUTH_URL" $pf9AuthUrl
    Set-EnvValue "PF9_USERNAME" $pf9Username
    Set-EnvValue "PF9_PASSWORD" $pf9Password
    Set-EnvValue "PF9_USER_DOMAIN" $pf9UserDomain
    Set-EnvValue "PF9_PROJECT_NAME" $pf9ProjectName
    Set-EnvValue "PF9_REGION_NAME" $pf9RegionName
    Set-EnvValue "PF9_REGION_URL" $pf9RegionUrl
    } # end if (-not $isDemo) — Platform9 credentials

    Write-Host ""
    # --- Database ---
    Write-Host "── Database Configuration ──" -ForegroundColor Yellow
    $pgUser = Prompt-Value "PostgreSQL Username" "pf9"
    $pgPassword = Prompt-Value "PostgreSQL Password (min 16 chars)" "" $true
    $pgDb = Prompt-Value "PostgreSQL Database Name" "pf9_mgmt"

    Set-EnvValue "POSTGRES_USER" $pgUser
    Set-EnvValue "POSTGRES_PASSWORD" $pgPassword
    Set-EnvValue "POSTGRES_DB" $pgDb
    Set-EnvValue "PF9_DB_USER" $pgUser
    Set-EnvValue "PF9_DB_PASSWORD" $pgPassword
    Set-EnvValue "PF9_DB_NAME" $pgDb

    Write-Host ""
    # --- pgAdmin ---
    Write-Host "── pgAdmin (Database Web UI) ──" -ForegroundColor Yellow
    $pgAdminEmail = Prompt-Value "pgAdmin login email" "admin@pf9-mgmt.local"
    $pgAdminPassword = Prompt-Value "pgAdmin login password (min 8 chars)" "" $true

    Set-EnvValue "PGADMIN_EMAIL" $pgAdminEmail
    Set-EnvValue "PGADMIN_PASSWORD" $pgAdminPassword

    Write-Host ""
    # --- LDAP ---
    Write-Host "── LDAP Directory Configuration ──" -ForegroundColor Yellow
    $ldapOrg = Prompt-Value "LDAP Organization Name" "Platform9 Management"
    $ldapDomain = Prompt-Value "LDAP Domain (e.g. company.com)" "pf9mgmt.local"
    $ldapAdminPw = Prompt-Value "LDAP Admin Password" "" $true
    $ldapConfigPw = Prompt-Value "LDAP Config Password" "" $true
    $ldapReadonlyPw = Prompt-Value "LDAP Readonly User Password" "" $true

    Set-EnvValue "LDAP_ORGANISATION" $ldapOrg
    Set-EnvValue "LDAP_DOMAIN" $ldapDomain
    Set-EnvValue "LDAP_ADMIN_PASSWORD" $ldapAdminPw
    Set-EnvValue "LDAP_CONFIG_PASSWORD" $ldapConfigPw
    Set-EnvValue "LDAP_READONLY_USER" "true"
    Set-EnvValue "LDAP_READONLY_PASSWORD" $ldapReadonlyPw

    # Derive LDAP base DN from domain (e.g. company.com -> dc=company,dc=com)
    $ldapBaseDn = ($ldapDomain -split '\.' | ForEach-Object { "dc=$_" }) -join ','
    Set-EnvValue "LDAP_BASE_DN" $ldapBaseDn
    Set-EnvValue "LDAP_USER_DN" "ou=users,$ldapBaseDn"
    Set-EnvValue "LDAP_GROUP_DN" "ou=groups,$ldapBaseDn"

    Write-Host ""
    # --- Admin User ---
    Write-Host "── Web Portal Admin ──" -ForegroundColor Yellow
    $adminUser = Prompt-Value "Admin Username (email)" "admin"
    $adminPassword = Prompt-Value "Admin Password" "" $true

    Set-EnvValue "DEFAULT_ADMIN_USER" $adminUser
    Set-EnvValue "DEFAULT_ADMIN_PASSWORD" $adminPassword

    Write-Host ""
    # --- Monitoring ---
    if (-not $isDemo) {
    Write-Host "── Monitoring Configuration ──" -ForegroundColor Yellow
    $pf9Hosts = Prompt-Value "PF9 Host IPs for metrics (comma-separated, or blank to skip)" ""
    if ($pf9Hosts) {
        Set-EnvValue "PF9_HOSTS" $pf9Hosts
    }

    Write-Host ""
    # --- Snapshot Service User ---
    Write-Host "── Snapshot Service User (Cross-Tenant Snapshots) ──" -ForegroundColor Yellow
    Write-Info "A dedicated service user enables creating snapshots in each tenant's project."
    Write-Info "This user must already exist in your Platform9 Identity."
    $snapshotUserEmail = Prompt-Value "Snapshot Service User Email (or blank to skip)" ""
    if ($snapshotUserEmail) {
        Set-EnvValue "SNAPSHOT_SERVICE_USER_EMAIL" $snapshotUserEmail
        
        $encChoice = Prompt-Value "Password storage: [1] Plaintext  [2] Fernet Encrypted" "1"
        if ($encChoice -eq "2") {
            Write-Info "Generating Fernet encryption key..."
            $pythonExeCheck = (Get-Command python -ErrorAction SilentlyContinue).Source
            if ($pythonExeCheck) {
                $fernetKey = & $pythonExeCheck -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>&1
                if ($LASTEXITCODE -eq 0) {
                    Write-Success "Generated Fernet key"
                    Set-EnvValue "SNAPSHOT_PASSWORD_KEY" $fernetKey
                    $svcPassword = Prompt-Value "Service User Password" "" $true
                    $encryptedPw = & $pythonExeCheck -c "from cryptography.fernet import Fernet; f=Fernet(b'$fernetKey'); print(f.encrypt(b'$svcPassword').decode())" 2>&1
                    Set-EnvValue "SNAPSHOT_USER_PASSWORD_ENCRYPTED" $encryptedPw
                    Write-Success "Password encrypted and saved"
                } else {
                    Write-Warning "cryptography package not available. Falling back to plaintext."
                    $svcPassword = Prompt-Value "Service User Password" "" $true
                    Set-EnvValue "SNAPSHOT_SERVICE_USER_PASSWORD" $svcPassword
                }
            } else {
                Write-Warning "Python not found. Falling back to plaintext."
                $svcPassword = Prompt-Value "Service User Password" "" $true
                Set-EnvValue "SNAPSHOT_SERVICE_USER_PASSWORD" $svcPassword
            }
        } else {
            $svcPassword = Prompt-Value "Service User Password" "" $true
            Set-EnvValue "SNAPSHOT_SERVICE_USER_PASSWORD" $svcPassword
        }
    } else {
        Write-Info "Skipping snapshot service user (snapshots will stay in service domain)"
    }
    } # end if (-not $isDemo) — Monitoring + Snapshot Service User

    Write-Host ""
    # --- Snapshot Restore ---
    Write-Host "── Snapshot Restore Configuration ──" -ForegroundColor Yellow
    Write-Info "The restore feature allows operators to restore VMs from Cinder snapshots."
    Write-Info "It is disabled by default and can be enabled later by editing .env."
    $restoreEnabled = Prompt-Value "Enable Snapshot Restore feature? (true/false)" "false"
    Set-EnvValue "RESTORE_ENABLED" $restoreEnabled

    if ($restoreEnabled -eq "true") {
        $restoreDryRun = Prompt-Value "Enable Dry-Run mode? (plans only, no execution) (true/false)" "false"
        Set-EnvValue "RESTORE_DRY_RUN" $restoreDryRun

        $restoreCleanup = Prompt-Value "Enable Volume Cleanup on failed restores? (true/false)" "false"
        Set-EnvValue "RESTORE_CLEANUP_VOLUMES" $restoreCleanup
    } else {
        Set-EnvValue "RESTORE_DRY_RUN" "false"
        Set-EnvValue "RESTORE_CLEANUP_VOLUMES" "false"
    }

    # --- Email Notifications (SMTP) ---
    Write-Host ""
    Write-Host "── Email Notifications (SMTP) ──" -ForegroundColor Yellow
    Write-Info "Email notifications can alert on drift events, snapshot failures, and compliance issues."
    $smtpEnabled = Prompt-Value "Enable email notifications? (true/false)" "false"
    Set-EnvValue "SMTP_ENABLED" $smtpEnabled

    if ($smtpEnabled -eq "true") {
        $smtpHost = Prompt-Value "SMTP server hostname or IP" ""
        $smtpPort = Prompt-Value "SMTP port" "25"
        $smtpTls = Prompt-Value "Use TLS? (true/false)" "false"
        Set-EnvValue "SMTP_HOST" $smtpHost
        Set-EnvValue "SMTP_PORT" $smtpPort
        Set-EnvValue "SMTP_USE_TLS" $smtpTls

        $smtpAuth = Prompt-Value "SMTP requires authentication? (y/n)" "n"
        if ($smtpAuth -eq 'y' -or $smtpAuth -eq 'Y') {
            $smtpUser = Prompt-Value "SMTP Username" ""
            $smtpPass = Prompt-Value "SMTP Password" "" $true
            Set-EnvValue "SMTP_USERNAME" $smtpUser
            Set-EnvValue "SMTP_PASSWORD" $smtpPass
        } else {
            Set-EnvValue "SMTP_USERNAME" ""
            Set-EnvValue "SMTP_PASSWORD" ""
        }

        $smtpFrom = Prompt-Value "From address for notification emails" "pf9-mgmt@$ldapDomain"
        Set-EnvValue "SMTP_FROM_ADDRESS" $smtpFrom

        $pollInterval = Prompt-Value "Notification poll interval in seconds" "120"
        Set-EnvValue "NOTIFICATION_POLL_INTERVAL_SECONDS" $pollInterval
        Set-EnvValue "NOTIFICATION_DIGEST_ENABLED" "true"
        Set-EnvValue "NOTIFICATION_DIGEST_HOUR_UTC" "8"
        Set-EnvValue "NOTIFICATION_LOOKBACK_SECONDS" "300"
        Set-EnvValue "HEALTH_ALERT_THRESHOLD" "50"

        Write-Success "SMTP notification settings configured"
    } else {
        Set-EnvValue "SMTP_HOST" ""
        Set-EnvValue "SMTP_PORT" "25"
        Set-EnvValue "SMTP_USE_TLS" "false"
        Set-EnvValue "SMTP_USERNAME" ""
        Set-EnvValue "SMTP_PASSWORD" ""
        Set-EnvValue "SMTP_FROM_ADDRESS" ""
        Write-Info "Email notifications disabled (can be enabled later in .env)"
    }

    # --- Metering Configuration ---
    Write-Host ""
    Write-Host "── Metering Configuration ──" -ForegroundColor Yellow
    Write-Info "Operational metering collects resource usage, snapshot, restore, and API metrics."
    $meteringEnabled = Prompt-Value "Enable operational metering? (true/false)" "true"
    Set-EnvValue "METERING_ENABLED" $meteringEnabled

    if ($meteringEnabled -eq "true") {
        $meteringInterval = Prompt-Value "Metering collection interval in minutes" "15"
        Set-EnvValue "METERING_POLL_INTERVAL" $meteringInterval
        $meteringRetention = Prompt-Value "Metering data retention in days" "90"
        Set-EnvValue "METERING_RETENTION_DAYS" $meteringRetention
        Write-Success "Metering configured (interval: ${meteringInterval}m, retention: ${meteringRetention}d)"
    } else {
        Set-EnvValue "METERING_POLL_INTERVAL" "15"
        Set-EnvValue "METERING_RETENTION_DAYS" "90"
        Write-Info "Metering disabled (can be enabled later in .env or via API)"
    }

    # --- JWT Secret ---
    Write-Host ""
    Write-Host "── Security ──" -ForegroundColor Yellow
    $jwtSecret = -join ((65..90) + (97..122) + (48..57) | Get-Random -Count 64 | ForEach-Object { [char]$_ })
    Set-EnvValue "JWT_SECRET_KEY" $jwtSecret
    Write-Success "Generated JWT secret key"

    Write-Host ""
    # --- LDAP Demo Users ---
    Write-Host "── LDAP Demo User Passwords (viewer/operator) ──" -ForegroundColor Yellow
    Write-Info "These users are created by setup_ldap.ps1. Leave blank to auto-generate."
    $viewerPw = Prompt-Value "Viewer user password (blank = auto-generate)" ""
    $operatorPw = Prompt-Value "Operator user password (blank = auto-generate)" ""
    if ($viewerPw) { Set-EnvValue "VIEWER_PASSWORD" $viewerPw }
    if ($operatorPw) { Set-EnvValue "OPERATOR_PASSWORD" $operatorPw }

    Write-Host ""
    Write-Success "Environment configuration complete!"
    Write-Info "Settings saved to .env"
    Write-Host ""
} else {
    Write-Success ".env file already exists"
    Write-Info "To reconfigure, delete .env and run deployment again"
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
    'POSTGRES_USER',
    'POSTGRES_PASSWORD',
    'POSTGRES_DB',
    'LDAP_ADMIN_PASSWORD',
    'DEFAULT_ADMIN_PASSWORD',
    'PGADMIN_PASSWORD',
    'JWT_SECRET_KEY'
)

# In production mode, Platform9 credentials are also required
$demoModeVal = $envMap['DEMO_MODE']
if ($demoModeVal -ne 'true') {
    $requiredVars += @('PF9_USERNAME', 'PF9_PASSWORD', 'PF9_AUTH_URL')
}

$missing = @()
foreach ($var in $requiredVars) {
    $val = $envMap[$var]
    if (-not $envMap.ContainsKey($var) -or [string]::IsNullOrWhiteSpace($val) -or $val -match '^<.*>$') {
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

# Validate snapshot service user configuration
Write-Info "Checking snapshot service user configuration..."

$snapshotEmail = $envMap['SNAPSHOT_SERVICE_USER_EMAIL']
$snapshotPassPlain = $envMap['SNAPSHOT_SERVICE_USER_PASSWORD']
$snapshotPassKey = $envMap['SNAPSHOT_PASSWORD_KEY']
$snapshotPassEnc = $envMap['SNAPSHOT_USER_PASSWORD_ENCRYPTED']

$hasPlainPassword = (-not [string]::IsNullOrWhiteSpace($snapshotPassPlain))
$hasEncryptedPassword = ((-not [string]::IsNullOrWhiteSpace($snapshotPassKey)) -and (-not [string]::IsNullOrWhiteSpace($snapshotPassEnc)))

if (-not [string]::IsNullOrWhiteSpace($snapshotEmail)) {
    Write-Success "Snapshot service user email: $snapshotEmail"
} else {
    Write-Warning "SNAPSHOT_SERVICE_USER_EMAIL not set — cross-tenant snapshots disabled"
}

if ($hasPlainPassword) {
    Write-Success "Snapshot service user password configured (plaintext)"
} elseif ($hasEncryptedPassword) {
    Write-Success "Snapshot service user password configured (encrypted)"
    # Verify password can be decrypted
    if ($pythonExe) {
        try {
            $decryptTest = & $pythonExe -c "
from cryptography.fernet import Fernet
import os, sys
try:
    f = Fernet('$snapshotPassKey'.encode())
    pw = f.decrypt('$snapshotPassEnc'.encode()).decode()
    print(f'OK:{len(pw)}')
except Exception as e:
    print(f'FAIL:{e}', file=sys.stderr)
    sys.exit(1)
" 2>&1
            if ($decryptTest -match "^OK:(\d+)$") {
                Write-Success "Encrypted password verified (length: $($Matches[1]))"
            } else {
                Write-Warning "Could not verify encrypted password: $decryptTest"
            }
        } catch {
            Write-Warning "Could not verify encrypted password (cryptography package may not be installed)"
        }
    }
} else {
    Write-Warning "No snapshot service user password configured"
    Write-Warning "Cross-tenant snapshots will fall back to admin session (service domain)"
    Write-Info "  Set SNAPSHOT_SERVICE_USER_PASSWORD or both"
    Write-Info "  SNAPSHOT_PASSWORD_KEY and SNAPSHOT_USER_PASSWORD_ENCRYPTED in .env"
    Write-Info "  See docs/SNAPSHOT_SERVICE_USER.md for details"
}

# Step 4: Prepare Directory Structure
Write-Section "Step 4: Creating Directory Structure"

$directories = @(
    ".\logs",
    ".\secrets",
    ".\reports",
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
    $requiredPackages = @('requests', 'aiohttp', 'openpyxl', 'psycopg2-binary', 'cryptography')
    
    foreach ($pkg in $requiredPackages) {
        try {
            & $pythonExe -m pip install --quiet $pkg 2>&1 | Out-Null
            Write-Success "Installed: $pkg"
        } catch {
            Write-Warning "Could not install: $pkg (may already be installed)"
        }
    }
    
    # Collect initial metrics if not skipped (skip in demo mode — seed script generates static cache)
    if (-not $SkipMetrics -and $envMap['DEMO_MODE'] -ne 'true') {
        Write-Info "Collecting initial metrics snapshot..."
        try {
            & $pythonExe "host_metrics_collector.py" "--once" 2>&1 | Out-Null
            Write-Success "Initial metrics collected"
        } catch {
            Write-Warning "Metrics collection failed (will retry later)"
        }
    } elseif ($envMap['DEMO_MODE'] -eq 'true') {
        Write-Info "Demo mode — skipping live metrics collection (seed script will generate static cache)"
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
    $metricsCmd = "cmd /c `"$pythonExe`" `"$ScriptDir\host_metrics_collector.py`" --once"
    
    try {
        schtasks /create /tn "PF9 Metrics Collection" /sc minute /mo 30 /st $start /tr $metricsCmd /ru $env:USERNAME /f 2>&1 | Out-Null
        Write-Success "Metrics collection task created (every 30 minutes)"
    } catch {
        Write-Warning "Could not create metrics task (may need admin privileges)"
        Write-Info "Run manually with: python host_metrics_collector.py"
    }
    
    Write-Info "Creating RVTools export task (daily at 2 AM)..."
    $rvtoolsCmd = "cmd /c `"$pythonExe`" `"$ScriptDir\pf9_rvtools.py`""
    
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


# Wait for services to initialize
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

# Step 8a: Run Metering Migration
Write-Section "Step 8a: Running Metering Migration"
Write-Info "Applying metering schema migration..."
try {
    Get-Content "db\migrate_metering.sql" | docker exec -i pf9_db psql -U $envMap['POSTGRES_USER'] -d pf9_mgmt 2>&1 | Out-Null
    Write-Success "Metering tables created/verified"
} catch {
    Write-Warning "Metering migration may have partially failed (non-critical)"
    Write-Info "Run manually: Get-Content db\migrate_metering.sql | docker exec -i pf9_db psql -U <user> -d pf9_mgmt"
}

# Step 8a2: Run Provisioning & Activity Log Migrations
Write-Section "Step 8a2: Running Provisioning & Activity Log Migrations"
$provisioningMigrations = @(
    @{File="db\migrate_provisioning.sql"; Desc="Provisioning tables (provisioning_jobs, provisioning_steps)"},
    @{File="db\migrate_activity_log.sql"; Desc="Activity log table"},
    @{File="db\migrate_tenant_permissions.sql"; Desc="Tenant disable/delete/resource_delete permissions"},
    @{File="db\migrate_reports_resources.sql"; Desc="Reports & Resource Management RBAC permissions"},
    @{File="db\migrate_technical_role_permissions.sql"; Desc="Technical role + missing resource permissions"},
    @{File="db\migrate_departments_navigation.sql"; Desc="Departments + Navigation visibility layer"},
    @{File="db\migrate_operator_permissions.sql"; Desc="Operator/viewer missing read permissions (networks, flavors, users)"},
    @{File="db\migrate_search.sql"; Desc="Ops Search tables (search_documents, search_indexer_state, pg_trgm)"},
    @{File="db\migrate_runbooks.sql"; Desc="Runbooks framework (runbooks, approval_policies, executions, approvals)"},
    @{File="db\migrate_new_runbooks.sql"; Desc="New runbooks v1.25 (7 additional engines + approval policies)"},
    @{File="db\migrate_fix_drift_columns.sql"; Desc="Drift detection: add missing columns, fix field-name mismatches"},
    @{File="db\migrate_copilot.sql"; Desc="Ops Copilot (copilot_history, copilot_feedback, copilot_config)"},
    @{File="db\migrate_os_tracking.sql"; Desc="OS tracking: image_id, os_distro, os_version on servers/images"},
    @{File="db\migrate_metadata_tables.sql"; Desc="Additional metadata: keypairs, server_groups, aggregates, volume_types, quotas"},
    @{File="db\migrate_snapshot_quota_batching.sql"; Desc="Snapshot quota-aware batching: batch progress, quota blocks, forecast runbook"},
    @{File="db\migrate_migration_planner.sql"; Desc="Migration Planner: 15 tables, RBAC permissions, nav groups, department visibility"},
    @{File="db\migrate_migration_schedule.sql"; Desc="Migration Planner: schedule-aware planning columns (duration, working hours, target VMs/day)"},
    @{File="db\migrate_migration_usage.sql"; Desc="Migration Planner: usage metrics, OS version, network name, vPartition columns"},
    @{File="db\migrate_migration_networks.sql"; Desc="Migration Planner: network infrastructure summary, tenant in_use_gb"},
    @{File="db\migrate_vm_usage_metrics.sql"; Desc="Migration Planner: vCPU/memory usage percentages from RVTools vCPU/vMemory sheets"},
    @{File="db\migrate_phase2_scoping.sql"; Desc="Migration Planner Phase 2: tenant scoping, target mapping, overcommit profiles, node sizing, PCD gap analysis"},
    @{File="db\migrate_cohorts_and_foundations.sql"; Desc="Migration Planner Phase 2.10: cohorts, VM status/mode-override, tenant priority, VM dependencies, network mappings, tenant readiness"},
    @{File="db\migrate_target_preseeding.sql"; Desc="Migration Planner v1.31.1: target name pre-seeding (source=default) + confirmed flags for network mappings and tenant targets"},
    @{File="db\migrate_cohort_fixes.sql"; Desc="Migration Planner v1.31.2: cohort schedule fields (duration_days, vms_per_day), fix target_project_name to use OrgVDC, backfill VLAN IDs from network names"},
    @{File="db\migrate_descriptions.sql"; Desc="Migration Planner v1.31.7: target_domain_description column on migration_tenants for PCD Domain description field"}
)
foreach ($mig in $provisioningMigrations) {
    Write-Info "Applying $($mig.Desc)..."
    try {
        Get-Content $mig.File | docker exec -i pf9_db psql -U $envMap['POSTGRES_USER'] -d pf9_mgmt 2>&1 | Out-Null
        Write-Success "$($mig.Desc) — OK"
    } catch {
        Write-Warning "$($mig.Desc) migration may have partially failed (non-critical)"
        Write-Info "Run manually: Get-Content $($mig.File) | docker exec -i pf9_db psql -U <user> -d pf9_mgmt"
    }
}

# Step 8b: Ensure admin user and superadmin permissions
Write-Section "Step 8b: Ensuring Admin User and Superadmin Permissions"
$defaultAdminUser = $envMap['DEFAULT_ADMIN_USER']
$defaultAdminPassword = $envMap['DEFAULT_ADMIN_PASSWORD']
if (-not $defaultAdminUser) { $defaultAdminUser = "admin" }
if (-not $defaultAdminPassword) {
    Write-Error "ERROR: DEFAULT_ADMIN_PASSWORD is not set in .env — refusing to use a default password."
    Write-Error "Please set DEFAULT_ADMIN_PASSWORD in your .env file and re-run deployment."
    exit 1
}

Write-Info "Ensuring admin user '$defaultAdminUser' is present in user_roles as superadmin..."
$ensureUserRole = "INSERT INTO user_roles (username, role, granted_by, granted_at, is_active) VALUES ('$defaultAdminUser', 'superadmin', 'system', now(), true) ON CONFLICT (username) DO UPDATE SET role='superadmin', granted_by='system', granted_at=now(), is_active=true;"
docker exec -i pf9_db psql -U $envMap['POSTGRES_USER'] -d $envMap['POSTGRES_DB'] -c "$ensureUserRole" | Out-Null
Write-Success "Admin user ensured in user_roles."

Write-Info "Ensuring wildcard permission for superadmin in role_permissions..."
$ensureSuperadminPerm = "INSERT INTO role_permissions (role, resource, action) VALUES ('superadmin', '*', 'admin') ON CONFLICT DO NOTHING;"
docker exec -i pf9_db psql -U $envMap['POSTGRES_USER'] -d $envMap['POSTGRES_DB'] -c "$ensureSuperadminPerm" | Out-Null
Write-Success "Wildcard permission for superadmin ensured."

# Step 9: Verify LDAP Initialization
Write-Section "Step 9: Verifying LDAP Directory"

try {
    $ldapBaseDN = $envMap['LDAP_BASE_DN']
    if (-not $ldapBaseDN) { $ldapBaseDN = "dc=pf9mgmt,dc=local" }
    $ldapCheck = & docker-compose exec -T ldap ldapsearch -x -H ldap://localhost -b "$ldapBaseDN" -D "cn=admin,$ldapBaseDN" -w $envMap['LDAP_ADMIN_PASSWORD'] "(objectClass=organizationalUnit)" dn 2>&1
    
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

# Step 9b: Demo Mode — Seed database & static metrics cache
if ($envMap['DEMO_MODE'] -eq 'true' -and $pythonExe) {
    Write-Section "Step 9b: Seeding Demo Data"
    Write-Info "Populating database with sample tenants, VMs, volumes, snapshots..."
    try {
        $seedArgs = @(
            "seed_demo_data.py",
            "--db-host", "localhost",
            "--db-port", "5432",
            "--db-name", $envMap['POSTGRES_DB'],
            "--db-user", $envMap['POSTGRES_USER'],
            "--db-pass", $envMap['POSTGRES_PASSWORD']
        )
        & $pythonExe @seedArgs 2>&1 | ForEach-Object { Write-Host $_ }
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Demo data seeded successfully"
        } else {
            Write-Warning "Demo seeding exited with code $LASTEXITCODE — check output above"
        }
    } catch {
        Write-Warning "Demo data seeding failed: $_"
        Write-Info "Run manually: python seed_demo_data.py"
    }
}

# Step 10: Health Checks
if (-not $SkipHealthCheck) {
    Write-Section "Step 10: Running Health Checks"
    
    $checks = @(
        @{Name="API"; Url="http://localhost:8000/health"; Critical=$true},
        @{Name="API Docs"; Url="http://localhost:8000/docs"; Critical=$false},
        @{Name="Monitoring"; Url="http://localhost:8001/health"; Critical=$true},
        @{Name="UI"; Url="http://localhost:5173"; Critical=$true},
        @{Name="pgAdmin"; Url="http://localhost:8080"; Critical=$false},
        @{Name="Notification Worker"; Url=$null; Container="pf9_notification_worker"; Critical=$false},
        @{Name="Backup Worker"; Url=$null; Container="pf9_backup_worker"; Critical=$false},
        @{Name="Metering Worker"; Url=$null; Container="pf9_metering_worker"; Critical=$false}
    )

    $allOk = $true
    $criticalFailed = $false
    
    foreach ($check in $checks) {
        Write-Info "Testing $($check.Name)..."
        Start-Sleep -Seconds 2

        if ($null -eq $check.Url) {
            # Container-only check (no HTTP endpoint)
            try {
                $containerStatus = docker inspect --format '{{.State.Status}}' $check.Container 2>&1
                if ($containerStatus -eq 'running') {
                    Write-Success "$($check.Name) container is running"
                } else {
                    Write-Warning "$($check.Name) container status: $containerStatus"
                    $allOk = $false
                }
            } catch {
                Write-Warning "$($check.Name) container not found (not critical)"
                $allOk = $false
            }
            continue
        }

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
Write-Host "  2. Log in with your LDAP admin credentials (configured during setup)" -ForegroundColor White
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

Write-Host "Snapshot Service User:" -ForegroundColor Cyan
if ($hasPlainPassword -or $hasEncryptedPassword) {
    $displayEmail = if ($snapshotEmail) { $snapshotEmail } else { "NOT SET" }
    $passType = if ($hasPlainPassword) { "plaintext" } else { "encrypted" }
    Write-Host "  Service User:          $displayEmail" -ForegroundColor White
    Write-Host "  Password:              Configured ($passType)" -ForegroundColor White
    Write-Host "  Cross-Tenant Mode:     ENABLED (snapshots in correct tenant projects)" -ForegroundColor Green
} else {
    Write-Host "  Service User:          NOT CONFIGURED" -ForegroundColor Yellow
    Write-Host "  Cross-Tenant Mode:     DISABLED (snapshots in service domain)" -ForegroundColor Yellow
    Write-Host "  To enable:             Set SNAPSHOT_SERVICE_USER_PASSWORD in .env" -ForegroundColor Yellow
    Write-Host "                         See docs/SNAPSHOT_SERVICE_USER.md" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "Snapshot Restore:" -ForegroundColor Cyan
$restoreEnabledVal = $envMap['RESTORE_ENABLED']
$restoreDryRunVal = $envMap['RESTORE_DRY_RUN']
$restoreCleanupVal = $envMap['RESTORE_CLEANUP_VOLUMES']
if ($restoreEnabledVal -eq "true") {
    Write-Host "  Feature:               ENABLED" -ForegroundColor Green
    if ($restoreDryRunVal -eq "true") {
        Write-Host "  Dry-Run Mode:          ON (plans only, no execution)" -ForegroundColor Yellow
    } else {
        Write-Host "  Dry-Run Mode:          OFF (full execution)" -ForegroundColor White
    }
    if ($restoreCleanupVal -eq "true") {
        Write-Host "  Volume Cleanup:        ON (cleanup on failure)" -ForegroundColor White
    } else {
        Write-Host "  Volume Cleanup:        OFF (orphaned volumes kept)" -ForegroundColor White
    }
    Write-Host "  Documentation:         docs/RESTORE_GUIDE.md" -ForegroundColor White
} else {
    Write-Host "  Feature:               DISABLED (default)" -ForegroundColor Yellow
    Write-Host "  To enable:             Set RESTORE_ENABLED=true in .env" -ForegroundColor Yellow
    Write-Host "                         See docs/RESTORE_GUIDE.md" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "Operational Metering:" -ForegroundColor Cyan
$meteringEnabledVal = $envMap['METERING_ENABLED']
$meteringIntervalVal = $envMap['METERING_POLL_INTERVAL']
if (-not $meteringIntervalVal) { $meteringIntervalVal = "15" }
if ($meteringEnabledVal -eq "true" -or -not $envMap.ContainsKey('METERING_ENABLED')) {
    Write-Host "  Feature:               ENABLED" -ForegroundColor Green
    Write-Host "  Collection Interval:   Every ${meteringIntervalVal} minutes" -ForegroundColor White
    Write-Host "  Worker Container:      pf9_metering_worker" -ForegroundColor White
    Write-Host "  UI Tab:                Metering (8 sub-tabs: overview, resources, snapshots, restores, API, efficiency, pricing, export)" -ForegroundColor White
    Write-Host "  API Endpoints:         /api/metering/* (20 endpoints + 6 CSV exports)" -ForegroundColor White
    Write-Host "  Pricing:               Multi-category (flavor, storage, snapshot, restore, volume, network)" -ForegroundColor White
    Write-Host "  Filters:               Dropdown selects populated from actual tenant/domain data" -ForegroundColor White
} else {
    Write-Host "  Feature:               DISABLED" -ForegroundColor Yellow
    Write-Host "  To enable:             Set METERING_ENABLED=true in .env" -ForegroundColor Yellow
    Write-Host "  Documentation:         See Metering section in docs/ADMIN_GUIDE.md" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "Email Notifications:" -ForegroundColor Cyan
$smtpEnabledVal = $envMap['SMTP_ENABLED']
$smtpHostVal = $envMap['SMTP_HOST']
if ($smtpEnabledVal -eq "true" -and -not [string]::IsNullOrWhiteSpace($smtpHostVal)) {
    $smtpPortVal = $envMap['SMTP_PORT']
    $smtpFromVal = $envMap['SMTP_FROM_ADDRESS']
    $smtpAuthVal = if ([string]::IsNullOrWhiteSpace($envMap['SMTP_USERNAME'])) { "No" } else { "Yes" }
    Write-Host "  Feature:               ENABLED" -ForegroundColor Green
    Write-Host "  SMTP Server:           ${smtpHostVal}:${smtpPortVal}" -ForegroundColor White
    Write-Host "  From Address:          $smtpFromVal" -ForegroundColor White
    Write-Host "  Authentication:        $smtpAuthVal" -ForegroundColor White
    Write-Host "  Worker Container:      pf9_notification_worker" -ForegroundColor White
    Write-Host "  UI Tab:                Notifications (preferences, history, settings)" -ForegroundColor White
} else {
    Write-Host "  Feature:               DISABLED" -ForegroundColor Yellow
    Write-Host "  To enable:             Set SMTP_ENABLED=true and SMTP_HOST in .env" -ForegroundColor Yellow
    Write-Host "  Documentation:         See SMTP section in docs/DEPLOYMENT_GUIDE.md" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "Customer Provisioning:" -ForegroundColor Cyan
Write-Host "  Feature:               ENABLED" -ForegroundColor Green
Write-Host "  UI Tabs:               Customer Provisioning, Domain Management, Activity Log" -ForegroundColor White
Write-Host "  API Endpoints:         /api/provisioning/* (12+ endpoints)" -ForegroundColor White
Write-Host "  Wizard:                5-step (Domain → Project → User/Role → Quotas → Network/SG)" -ForegroundColor White
Write-Host "  Domain Management:     Enable/disable/delete domains with resource inspection" -ForegroundColor White
Write-Host "  Activity Log:          Central audit trail for all provisioning operations" -ForegroundColor White
Write-Host "  Network Naming:        {tenant_base}_extnet_vlan_{vlanid} (auto-derived, user-overrideable)" -ForegroundColor White
Write-Host "  Admin Notifications:   Rich tenant_provisioned email with full inventory (user, network, SG, quotas)" -ForegroundColor White
Write-Host "  RBAC:                  admin/superadmin with granular tenant_disable/tenant_delete/resource_delete" -ForegroundColor White
Write-Host ""

Write-Host "Ops Search (Ops Assistant):" -ForegroundColor Cyan
Write-Host "  Feature:               ENABLED" -ForegroundColor Green
Write-Host "  UI Tab:                Ops Search (full-text + similarity + intent + smart queries)" -ForegroundColor White
Write-Host "  Worker:                pf9_search_worker (incremental indexer, default 5-min interval)" -ForegroundColor White
Write-Host "  API Endpoints:         /api/search (search, similar, intent, stats, reindex, smart, smart/help)" -ForegroundColor White
Write-Host "  Smart Queries:         26 templates (VM status, quotas, capacity, networks, roles, drift, etc.)" -ForegroundColor White
Write-Host "  Scope Filters:         Domain/Tenant dropdown filters — 20 of 26 queries are scope-aware" -ForegroundColor White
Write-Host "  Quota Metering:        Per-project usage (vCPUs, RAM, VMs, volumes, storage, FIPs, SGs)" -ForegroundColor White
Write-Host "  Doc Types:             29 indexed types (VMs, volumes, users, audit, drift, snapshots, roles...)" -ForegroundColor White
Write-Host "  RBAC:                  viewer/operator=search:read, admin/superadmin=search:admin" -ForegroundColor White
Write-Host ""

Write-Host "Runbooks (Policy-as-Code):" -ForegroundColor Cyan
Write-Host "  Feature:               ENABLED" -ForegroundColor Green
Write-Host "  UI Tab:                Runbooks (catalogue, execution history, approvals, policy editor)" -ForegroundColor White
Write-Host "  API Endpoints:         /api/runbooks (list, trigger, approve, reject, cancel, history, policies, stats)" -ForegroundColor White
Write-Host "  Built-in Runbooks:     5 (Stuck VM, Orphan Cleanup, SG Audit, Quota Check, Diagnostics Bundle)" -ForegroundColor White
Write-Host "  Approval Workflows:    Flexible trigger_role → approver_role mapping per runbook" -ForegroundColor White
Write-Host "  Approval Modes:        auto_approve, single_approval, multi_approval" -ForegroundColor White
Write-Host "  Dry-Run:               First-class concept — all runbooks support scan-only mode" -ForegroundColor White
Write-Host "  RBAC:                  viewer=read, operator=read+trigger, admin/superadmin=full+policies" -ForegroundColor White
Write-Host ""

Write-Success "System is ready for use!"
