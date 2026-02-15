# LDAP Directory Setup Script
# This script initializes the LDAP directory with default users and groups

Write-Host "=== LDAP Directory Initialization ===" -ForegroundColor Cyan

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

# Default passwords for demo users — override via VIEWER_PASSWORD / OPERATOR_PASSWORD in .env
if (-not $VIEWER_PASSWORD) {
    Write-Host "WARNING: VIEWER_PASSWORD not set in .env — generating a random password" -ForegroundColor Yellow
    $VIEWER_PASSWORD = -join ((65..90) + (97..122) + (48..57) | Get-Random -Count 16 | ForEach-Object { [char]$_ })
}
if (-not $OPERATOR_PASSWORD) {
    Write-Host "WARNING: OPERATOR_PASSWORD not set in .env — generating a random password" -ForegroundColor Yellow
    $OPERATOR_PASSWORD = -join ((65..90) + (97..122) + (48..57) | Get-Random -Count 16 | ForEach-Object { [char]$_ })
}

# Wait for LDAP service to be ready
Write-Host "Waiting for LDAP service to be ready..." -ForegroundColor Yellow
do {
    Start-Sleep -Seconds 2
    $ldapStatus = docker exec pf9_ldap ldapsearch -H ldap://localhost -x -b $LDAP_BASE_DN -s base "(objectclass=*)" 2>$null
} while (-not $ldapStatus)

Write-Host "✓ LDAP service is ready" -ForegroundColor Green

# Create LDIF files for initial setup
$ldifDir = "ldap_setup"
New-Item -ItemType Directory -Path $ldifDir -Force | Out-Null

# 1. Create organizational units
@"
# Create organizational units
dn: $LDAP_USER_DN
objectClass: organizationalUnit
ou: users

dn: $LDAP_GROUP_DN
objectClass: organizationalUnit
ou: groups
"@ | Out-File -FilePath "$ldifDir\01_create_ous.ldif" -Encoding UTF8

# 2. Create groups for RBAC roles
@"
# Create RBAC groups
dn: cn=pf9_viewers,$LDAP_GROUP_DN
objectClass: groupOfNames
cn: pf9_viewers
description: Platform9 Viewers - Read-only access
member: cn=placeholder,$LDAP_USER_DN

dn: cn=pf9_operators,$LDAP_GROUP_DN
objectClass: groupOfNames
cn: pf9_operators
description: Platform9 Operators - Can perform operations
member: cn=placeholder,$LDAP_USER_DN

dn: cn=pf9_admins,$LDAP_GROUP_DN
objectClass: groupOfNames
cn: pf9_admins
description: Platform9 Administrators - Full access
member: cn=placeholder,$LDAP_USER_DN

dn: cn=pf9_superadmins,$LDAP_GROUP_DN
objectClass: groupOfNames
cn: pf9_superadmins
description: Platform9 Super Administrators - Full system access
member: cn=placeholder,$LDAP_USER_DN
"@ | Out-File -FilePath "$ldifDir\02_create_groups.ldif" -Encoding UTF8

# 3. Create default users
@"
# Default users for Management System Authentication
dn: cn=$DEFAULT_ADMIN_USER,$LDAP_USER_DN
objectClass: person
objectClass: inetOrgPerson
cn: $DEFAULT_ADMIN_USER
sn: Administrator
uid: $DEFAULT_ADMIN_USER
mail: $DEFAULT_ADMIN_USER
userPassword: {SSHA}$(docker exec pf9_ldap slappasswd -s "$DEFAULT_ADMIN_PASSWORD")
description: Management System Administrator

dn: cn=viewer,$LDAP_USER_DN
objectClass: person
objectClass: inetOrgPerson
cn: viewer
sn: Viewer
uid: viewer
mail: viewer
userPassword: {SSHA}$(docker exec pf9_ldap slappasswd -s "$VIEWER_PASSWORD")
description: Read-only viewer user

dn: cn=operator,$LDAP_USER_DN
objectClass: person
objectClass: inetOrgPerson
cn: operator
sn: Operator
uid: operator
mail: operator
userPassword: {SSHA}$(docker exec pf9_ldap slappasswd -s "$OPERATOR_PASSWORD")
description: Operations user
"@ | Out-File -FilePath "$ldifDir\03_create_users.ldif" -Encoding UTF8

# 4. Add users to groups
@"
# Add users to appropriate groups
dn: cn=pf9_superadmins,$LDAP_GROUP_DN
changetype: modify
delete: member
member: cn=placeholder,$LDAP_USER_DN
-
add: member
member: cn=$DEFAULT_ADMIN_USER,$LDAP_USER_DN

dn: cn=pf9_admins,$LDAP_GROUP_DN
changetype: modify
delete: member
member: cn=placeholder,$LDAP_USER_DN
-
add: member
member: cn=`$DEFAULT_ADMIN_USER,`$LDAP_USER_DN

dn: cn=pf9_operators,$LDAP_GROUP_DN
changetype: modify
delete: member
member: cn=placeholder,$LDAP_USER_DN
-
add: member
member: cn=operator,$LDAP_USER_DN

dn: cn=pf9_viewers,$LDAP_GROUP_DN
changetype: modify
delete: member
member: cn=placeholder,$LDAP_USER_DN
-
add: member
member: cn=viewer,$LDAP_USER_DN
"@ | Out-File -FilePath "$ldifDir\04_assign_groups.ldif" -Encoding UTF8

# Execute LDIF files
Write-Host "Creating organizational units..." -ForegroundColor Yellow
docker exec pf9_ldap ldapadd -H ldap://localhost -x -D "cn=admin,$LDAP_BASE_DN" -w $LDAP_ADMIN_PASSWORD -f "/tmp/01_create_ous.ldif" 2>$null
if ($LASTEXITCODE -eq 0) { Write-Host "✓ Organizational units created" -ForegroundColor Green }

Write-Host "Creating RBAC groups..." -ForegroundColor Yellow
docker exec pf9_ldap ldapadd -H ldap://localhost -x -D "cn=admin,$LDAP_BASE_DN" -w $LDAP_ADMIN_PASSWORD -f "/tmp/02_create_groups.ldif" 2>$null
if ($LASTEXITCODE -eq 0) { Write-Host "✓ RBAC groups created" -ForegroundColor Green }

Write-Host "Creating default users..." -ForegroundColor Yellow
docker exec pf9_ldap ldapadd -H ldap://localhost -x -D "cn=admin,$LDAP_BASE_DN" -w $LDAP_ADMIN_PASSWORD -f "/tmp/03_create_users.ldif" 2>$null
if ($LASTEXITCODE -eq 0) { Write-Host "✓ Default users created" -ForegroundColor Green }

Write-Host "Assigning users to groups..." -ForegroundColor Yellow
docker exec pf9_ldap ldapmodify -H ldap://localhost -x -D "cn=admin,$LDAP_BASE_DN" -w $LDAP_ADMIN_PASSWORD -f "/tmp/04_assign_groups.ldif" 2>$null
if ($LASTEXITCODE -eq 0) { Write-Host "✓ Users assigned to groups" -ForegroundColor Green }

# Copy LDIF files to container
docker exec pf9_ldap mkdir -p /tmp/ldap_setup
Get-ChildItem -Path $ldifDir -Name | ForEach-Object {
    docker cp "$ldifDir\$_" "pf9_ldap:/tmp/$_"
}

Write-Host ""
Write-Host "=== LDAP Directory Setup Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Management System Users Created:" -ForegroundColor Cyan
Write-Host "  • $DEFAULT_ADMIN_USER/(configured via DEFAULT_ADMIN_PASSWORD) - System Administrator" -ForegroundColor White
Write-Host "  • operator/(configured via OPERATOR_PASSWORD) - Operator" -ForegroundColor White
Write-Host "  • viewer/(configured via VIEWER_PASSWORD)     - Viewer" -ForegroundColor White
Write-Host ""
Write-Host "LDAP Management:" -ForegroundColor Cyan
Write-Host "  • Web Admin: http://localhost:$LDAP_ADMIN_PORT" -ForegroundColor White
Write-Host "  • Admin DN: cn=admin,$LDAP_BASE_DN" -ForegroundColor White
Write-Host "  • Password: ********** (set via LDAP_ADMIN_PASSWORD in .env)" -ForegroundColor White

# Test authentication
Write-Host ""
Write-Host "Testing authentication..." -ForegroundColor Yellow
$loginTest = curl -s -X POST -H "Content-Type: application/json" -d "{`"username`":`"$DEFAULT_ADMIN_USER`",`"password`":`"$DEFAULT_ADMIN_PASSWORD`"}" http://localhost:8000/auth/login
if ($loginTest) {
    Write-Host "✓ Authentication is working!" -ForegroundColor Green
} else {
    Write-Host "⚠ Authentication test failed" -ForegroundColor Red
}

# Cleanup
Remove-Item -Path $ldifDir -Recurse -Force