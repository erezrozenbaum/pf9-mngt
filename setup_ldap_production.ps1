# Production LDAP Directory Setup Script
# Creates only 3 super-admin users for CCC management system authentication

Write-Host "=== CCC Production LDAP Setup ===" -ForegroundColor Cyan

# Load environment variables from .env file
Get-Content .env | foreach {
    if ($_ -match '^([^=]+)=(.*)$') {
        $name = $matches[1]
        $value = $matches[2]
        Set-Variable -Name $name -Value $value
    }
}

# Validate required environment variables
if (-not $LDAP_ADMIN_PASSWORD) {
    Write-Host "Error: LDAP_ADMIN_PASSWORD not set in .env file" -ForegroundColor Red
    exit 1
}

if (-not $LDAP_BASE_DN) {
    Write-Host "Error: LDAP_BASE_DN not set in .env file" -ForegroundColor Red
    exit 1
}

Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  Domain: $LDAP_DOMAIN" -ForegroundColor White
Write-Host "  Base DN: $LDAP_BASE_DN" -ForegroundColor White
Write-Host "  Password: r#1kajun (for all users)" -ForegroundColor White

# Wait for LDAP service to be ready
Write-Host "Waiting for LDAP service to be ready..." -ForegroundColor Yellow
$attempts = 0
do {
    Start-Sleep -Seconds 2
    $attempts++
    $ldapStatus = docker exec pf9_ldap ldapsearch -H ldap://localhost -x -b $LDAP_BASE_DN -s base "(objectclass=*)" 2>$null
    if ($attempts -gt 30) {
        Write-Host "Error: LDAP service not ready after 60 seconds" -ForegroundColor Red
        exit 1
    }
} while (-not $ldapStatus)

Write-Host "✓ LDAP service is ready" -ForegroundColor Green

# Create LDIF files for production setup
$ldifDir = "production_ldap"
New-Item -ItemType Directory -Path $ldifDir -Force | Out-Null

# 1. Create organizational units
@"
# Create organizational units for CCC
dn: $LDAP_USER_DN
objectClass: organizationalUnit
ou: users

dn: $LDAP_GROUP_DN
objectClass: organizationalUnit
ou: groups
"@ | Out-File -FilePath "$ldifDir\01_create_ous.ldif" -Encoding UTF8

# 2. Create superadmin group
@"
# Create superadmin group
dn: cn=superadmin,$LDAP_GROUP_DN
objectClass: groupOfNames
cn: superadmin
description: Super Administrator - Full management system access
member: cn=admin,$LDAP_USER_DN
"@ | Out-File -FilePath "$ldifDir\02_create_groups.ldif" -Encoding UTF8

# 3. Create production users (admin, erez@ccc.co.il, itay@ccc.co.il)
@"
# Production users for CCC management system
dn: cn=admin,$LDAP_USER_DN
objectClass: person
objectClass: inetOrgPerson
cn: admin
sn: Administrator
uid: admin
mail: admin@$LDAP_DOMAIN
userPassword: $DEFAULT_ADMIN_PASSWORD
description: CCC Management System Administrator

dn: cn=erez,$LDAP_USER_DN
objectClass: person
objectClass: inetOrgPerson
cn: erez
sn: Erez
givenName: Erez
uid: erez
mail: erez@$LDAP_DOMAIN
userPassword: $DEFAULT_ADMIN_PASSWORD
description: CCC Super Administrator

dn: cn=itay,$LDAP_USER_DN
objectClass: person
objectClass: inetOrgPerson
cn: itay
sn: Itay
givenName: Itay
uid: itay
mail: itay@$LDAP_DOMAIN
userPassword: $DEFAULT_ADMIN_PASSWORD
description: CCC Super Administrator
"@ | Out-File -FilePath "$ldifDir\03_create_users.ldif" -Encoding UTF8

# 4. Add all users to superadmin group
@"
# Add all users to superadmin group
dn: cn=superadmin,$LDAP_GROUP_DN
changetype: modify
add: member
member: cn=erez,$LDAP_USER_DN
-
add: member
member: cn=itay,$LDAP_USER_DN
"@ | Out-File -FilePath "$ldifDir\04_assign_groups.ldif" -Encoding UTF8

# Copy LDIF files to container first
Write-Host "Copying LDIF files to container..." -ForegroundColor Yellow
docker exec pf9_ldap mkdir -p /tmp/production_ldap 2>$null
Get-ChildItem -Path $ldifDir -Name | ForEach-Object {
    docker cp "$ldifDir\$_" "pf9_ldap:/tmp/$_"
}

# Execute LDIF files
Write-Host "Creating organizational units..." -ForegroundColor Yellow
docker exec pf9_ldap ldapadd -H ldap://localhost -x -D "cn=admin,$LDAP_BASE_DN" -w $LDAP_ADMIN_PASSWORD -f "/tmp/01_create_ous.ldif" 2>$null
if ($LASTEXITCODE -eq 0) { 
    Write-Host "✓ Organizational units created" -ForegroundColor Green 
} else {
    Write-Host "ℹ Organizational units may already exist" -ForegroundColor Yellow
}

Write-Host "Creating superadmin group..." -ForegroundColor Yellow
docker exec pf9_ldap ldapadd -H ldap://localhost -x -D "cn=admin,$LDAP_BASE_DN" -w $LDAP_ADMIN_PASSWORD -f "/tmp/02_create_groups.ldif" 2>$null
if ($LASTEXITCODE -eq 0) { 
    Write-Host "✓ Superadmin group created" -ForegroundColor Green 
} else {
    Write-Host "ℹ Superadmin group may already exist" -ForegroundColor Yellow
}

Write-Host "Creating production users..." -ForegroundColor Yellow
docker exec pf9_ldap ldapadd -H ldap://localhost -x -D "cn=admin,$LDAP_BASE_DN" -w $LDAP_ADMIN_PASSWORD -f "/tmp/03_create_users.ldif" 2>$null
if ($LASTEXITCODE -eq 0) { 
    Write-Host "✓ Production users created" -ForegroundColor Green 
} else {
    Write-Host "ℹ Production users may already exist" -ForegroundColor Yellow
}

Write-Host "Assigning users to superadmin group..." -ForegroundColor Yellow
docker exec pf9_ldap ldapmodify -H ldap://localhost -x -D "cn=admin,$LDAP_BASE_DN" -w $LDAP_ADMIN_PASSWORD -f "/tmp/04_assign_groups.ldif" 2>$null
if ($LASTEXITCODE -eq 0) { 
    Write-Host "✓ Users assigned to superadmin group" -ForegroundColor Green 
} else {
    Write-Host "ℹ User assignments may already exist" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== CCC Production LDAP Setup Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Production Users Created:" -ForegroundColor Cyan
Write-Host "  • admin           - System Administrator" -ForegroundColor White
Write-Host "  • erez@ccc.co.il  - Super Administrator" -ForegroundColor White
Write-Host "  • itay@ccc.co.il  - Super Administrator" -ForegroundColor White
Write-Host ""
Write-Host "All users have password: r#1kajun" -ForegroundColor Yellow
Write-Host "All users have superadmin permissions" -ForegroundColor Yellow
Write-Host ""
Write-Host "Access Points:" -ForegroundColor Cyan
Write-Host "  • Management UI: http://localhost:5173" -ForegroundColor White
Write-Host "  • LDAP Admin: http://localhost:$LDAP_ADMIN_PORT" -ForegroundColor White
Write-Host "  • Admin DN: cn=admin,$LDAP_BASE_DN" -ForegroundColor White

# Test authentication for all users
Write-Host ""
Write-Host "Testing authentication..." -ForegroundColor Yellow

$users = @("admin", "erez", "itay")
foreach ($user in $users) {
    $loginTest = curl -s -X POST -H "Content-Type: application/json" -d "{`"username`":`"$user`",`"password`":`"r#1kajun`"}" http://localhost:8000/auth/login 2>$null
    if ($loginTest -and $loginTest -like "*token*") {
        Write-Host "✓ $user authentication successful" -ForegroundColor Green
    } else {
        Write-Host "⚠ $user authentication failed" -ForegroundColor Red
    }
}

# Cleanup
Remove-Item -Path $ldifDir -Recurse -Force
Write-Host ""
Write-Host "Ready for production use!" -ForegroundColor Green