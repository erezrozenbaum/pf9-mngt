# PF9 Management System - LDAP Setup Script for Windows
# This script helps initialize the LDAP directory after container startup

param(
    [string]$LdapContainer = "pf9_ldap",
    [string]$AdminPassword = $env:LDAP_ADMIN_PASSWORD,
    [string]$BaseDN = $env:LDAP_BASE_DN,
    [string]$DefaultAdminUser = $(if ($env:DEFAULT_ADMIN_USER) { $env:DEFAULT_ADMIN_USER } else { "admin" }),
    [string]$DefaultAdminPassword = $env:DEFAULT_ADMIN_PASSWORD
)

Write-Host "PF9 Management System - LDAP Setup" -ForegroundColor Green

if (-not $AdminPassword) {
    $AdminPassword = Read-Host "Enter LDAP Admin Password" -AsSecureString
    $AdminPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($AdminPassword))
}

if (-not $BaseDN) {
    $BaseDN = "dc=pf9mgmt,dc=local"
}

if (-not $DefaultAdminPassword) {
    $DefaultAdminPassword = Read-Host "Enter Default Admin Password" -AsSecureString
    $DefaultAdminPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($DefaultAdminPassword))
}

Write-Host "Setting up LDAP directory structure..." -ForegroundColor Yellow

# Check if LDAP container is running
$containerStatus = docker ps --filter "name=$LdapContainer" --format "table {{.Status}}"
if (-not $containerStatus -or $containerStatus -notmatch "Up") {
    Write-Host "LDAP container '$LdapContainer' is not running. Starting services..." -ForegroundColor Red
    docker-compose up -d ldap
    Start-Sleep 10
}

Write-Host "Executing LDAP setup script in container..." -ForegroundColor Yellow

# Run the setup script inside the container
docker exec $LdapContainer bash -c "
export LDAP_BASE_DN='$BaseDN'
export LDAP_ADMIN_PASSWORD='$AdminPassword'
export DEFAULT_ADMIN_USER='$DefaultAdminUser'
export DEFAULT_ADMIN_PASSWORD='$DefaultAdminPassword'
bash /container/service/setup.sh
"

Write-Host "LDAP setup completed!" -ForegroundColor Green
Write-Host "You can now:" -ForegroundColor Cyan
Write-Host "  1. Access phpLDAPadmin at http://localhost:8081" -ForegroundColor White
Write-Host "  2. Login with DN: cn=admin,$BaseDN" -ForegroundColor White
Write-Host "  3. Use the API login endpoint with username 'admin'" -ForegroundColor White
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Test authentication: POST http://localhost:8000/auth/login" -ForegroundColor White
Write-Host "  2. Create additional users via phpLDAPadmin" -ForegroundColor White
Write-Host "  3. Assign roles via the API: POST http://localhost:8000/auth/users/{username}/role" -ForegroundColor White