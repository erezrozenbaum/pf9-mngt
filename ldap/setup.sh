#!/bin/bash

# LDAP Directory Setup Script
# This script initializes the LDAP directory structure for the PF9 Management System

set -e

# Configuration from environment variables
LDAP_DOMAIN=${LDAP_DOMAIN:-"pf9mgmt.local"}
LDAP_BASE_DN=${LDAP_BASE_DN:-"dc=pf9mgmt,dc=local"}
LDAP_ADMIN_PASSWORD=${LDAP_ADMIN_PASSWORD:-"admin"}
DEFAULT_ADMIN_USER=${DEFAULT_ADMIN_USER:-"admin"}
DEFAULT_ADMIN_PASSWORD=${DEFAULT_ADMIN_PASSWORD:-"admin"}

echo "Setting up LDAP directory structure for domain: $LDAP_DOMAIN"

# Wait for LDAP server to be ready
echo "Waiting for LDAP server to be ready..."
until ldapsearch -x -H ldap://ldap:389 -b "$LDAP_BASE_DN" -s base > /dev/null 2>&1; do
    echo "LDAP server not ready yet, waiting 5 seconds..."
    sleep 5
done

echo "LDAP server is ready!"

# Create LDIF for organizational units
cat > /tmp/init_structure.ldif << EOF
# Create organizational units
dn: ou=users,$LDAP_BASE_DN
objectClass: organizationalUnit
ou: users
description: PF9 Management System Users

dn: ou=groups,$LDAP_BASE_DN
objectClass: organizationalUnit
ou: groups
description: PF9 Management System Groups

# Create default groups
dn: cn=admins,ou=groups,$LDAP_BASE_DN
objectClass: groupOfNames
cn: admins
description: System Administrators
member: uid=$DEFAULT_ADMIN_USER,ou=users,$LDAP_BASE_DN

dn: cn=operators,ou=groups,$LDAP_BASE_DN
objectClass: groupOfNames
cn: operators
description: System Operators
member: uid=$DEFAULT_ADMIN_USER,ou=users,$LDAP_BASE_DN

dn: cn=viewers,ou=groups,$LDAP_BASE_DN
objectClass: groupOfNames
cn: viewers
description: Read-only Users
member: uid=$DEFAULT_ADMIN_USER,ou=users,$LDAP_BASE_DN
EOF

# Create LDIF for default admin user
cat > /tmp/admin_user.ldif << EOF
# Create default admin user
dn: uid=$DEFAULT_ADMIN_USER,ou=users,$LDAP_BASE_DN
objectClass: inetOrgPerson
objectClass: posixAccount
objectClass: shadowAccount
uid: $DEFAULT_ADMIN_USER
cn: System Administrator
sn: Administrator
givenName: System
mail: admin@$LDAP_DOMAIN
userPassword: {SSHA}$(slappasswd -s "$DEFAULT_ADMIN_PASSWORD" -h {SSHA})
uidNumber: 1001
gidNumber: 1001
homeDirectory: /home/$DEFAULT_ADMIN_USER
loginShell: /bin/bash
description: Default administrator for PF9 Management System
EOF

echo "Creating organizational structure..."
ldapadd -x -H ldap://ldap:389 -D "cn=admin,$LDAP_BASE_DN" -w "$LDAP_ADMIN_PASSWORD" -f /tmp/init_structure.ldif

echo "Creating default admin user..."
ldapadd -x -H ldap://ldap:389 -D "cn=admin,$LDAP_BASE_DN" -w "$LDAP_ADMIN_PASSWORD" -f /tmp/admin_user.ldif

echo "LDAP directory initialization completed successfully!"

# Test the setup
echo "Testing LDAP setup..."
ldapsearch -x -H ldap://ldap:389 -D "cn=admin,$LDAP_BASE_DN" -w "$LDAP_ADMIN_PASSWORD" -b "ou=users,$LDAP_BASE_DN" "(uid=$DEFAULT_ADMIN_USER)"

echo "LDAP setup verification completed!"

# Cleanup temporary files
rm -f /tmp/init_structure.ldif /tmp/admin_user.ldif

echo "LDAP directory setup completed successfully!"
echo "Default admin user: $DEFAULT_ADMIN_USER"
echo "You can access phpLDAPadmin to manage users and groups."