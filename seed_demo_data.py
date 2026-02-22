#!/usr/bin/env python3
"""
Demo Data Seeder for PF9 Management Portal
-------------------------------------------
Populates PostgreSQL with realistic demo data so the portal can be evaluated
without a live Platform9 environment.

Usage:
    python seed_demo_data.py              # Uses DATABASE_URL or individual PF9_DB_* env vars
    python seed_demo_data.py --db-host localhost --db-port 5432 --db-name pf9_mgmt --db-user pf9 --db-pass secret

Tables seeded:
    domains, projects, hypervisors, flavors, images,
    servers, volumes, snapshots, networks, subnets, routers,
    security_groups, security_group_rules,
    users, roles, role_assignments,
    inventory_runs, snapshot_policy_sets, snapshot_assignments,
    compliance_reports, compliance_details,
    drift_rules, drift_events,
    activity_log, metering_config, metering_flavor_pricing,
    backup_config, runbooks, runbook_approval_policies

All INSERTs use ON CONFLICT DO NOTHING so the script is idempotent.
"""
import argparse
import json
import os
import sys
import uuid
import random
import hashlib
from datetime import datetime, timedelta, timezone

try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def uid():
    return str(uuid.uuid4())

def now():
    return datetime.now(timezone.utc)

def ago(**kw):
    return now() - timedelta(**kw)

def change_hash(data: dict) -> str:
    return hashlib.md5(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()

# ---------------------------------------------------------------------------
# Demo data constants
# ---------------------------------------------------------------------------
DEMO_DOMAINS = [
    {"id": "d-acme-corp",    "name": "acme-corp.com"},
    {"id": "d-globex-inc",   "name": "globex-inc.com"},
    {"id": "d-initech",      "name": "initech.io"},
]

DEMO_PROJECTS = [
    # acme-corp
    {"id": "p-acme-prod",    "name": "production",    "domain_id": "d-acme-corp"},
    {"id": "p-acme-staging", "name": "staging",        "domain_id": "d-acme-corp"},
    {"id": "p-acme-dev",     "name": "development",    "domain_id": "d-acme-corp"},
    # globex
    {"id": "p-globex-prod",  "name": "production",    "domain_id": "d-globex-inc"},
    {"id": "p-globex-dr",    "name": "disaster-recovery", "domain_id": "d-globex-inc"},
    # initech
    {"id": "p-initech-prod", "name": "production",    "domain_id": "d-initech"},
    {"id": "p-initech-test", "name": "testing",        "domain_id": "d-initech"},
]

DEMO_HYPERVISORS = [
    {"id": "h-node01", "hostname": "kvm-node-01", "hypervisor_type": "QEMU", "vcpus": 64, "memory_mb": 262144, "local_gb": 2000, "state": "up", "status": "enabled"},
    {"id": "h-node02", "hostname": "kvm-node-02", "hypervisor_type": "QEMU", "vcpus": 64, "memory_mb": 262144, "local_gb": 2000, "state": "up", "status": "enabled"},
    {"id": "h-node03", "hostname": "kvm-node-03", "hypervisor_type": "QEMU", "vcpus": 48, "memory_mb": 131072, "local_gb": 1000, "state": "up", "status": "enabled"},
    {"id": "h-node04", "hostname": "kvm-node-04", "hypervisor_type": "QEMU", "vcpus": 48, "memory_mb": 131072, "local_gb": 1000, "state": "up", "status": "enabled"},
    {"id": "h-node05", "hostname": "kvm-node-05", "hypervisor_type": "QEMU", "vcpus": 32, "memory_mb": 65536,  "local_gb": 500,  "state": "up", "status": "disabled"},
]

DEMO_FLAVORS = [
    {"id": "f-small",   "name": "m1.small",   "vcpus": 1, "ram_mb": 2048,  "disk_gb": 20,  "ephemeral_gb": 0, "swap_mb": 0, "is_public": True},
    {"id": "f-medium",  "name": "m1.medium",  "vcpus": 2, "ram_mb": 4096,  "disk_gb": 40,  "ephemeral_gb": 0, "swap_mb": 0, "is_public": True},
    {"id": "f-large",   "name": "m1.large",   "vcpus": 4, "ram_mb": 8192,  "disk_gb": 80,  "ephemeral_gb": 0, "swap_mb": 0, "is_public": True},
    {"id": "f-xlarge",  "name": "m1.xlarge",  "vcpus": 8, "ram_mb": 16384, "disk_gb": 160, "ephemeral_gb": 0, "swap_mb": 0, "is_public": True},
    {"id": "f-2xlarge", "name": "m1.2xlarge", "vcpus": 16,"ram_mb": 32768, "disk_gb": 320, "ephemeral_gb": 0, "swap_mb": 0, "is_public": True},
    {"id": "f-db",      "name": "db.large",   "vcpus": 4, "ram_mb": 16384, "disk_gb": 200, "ephemeral_gb": 0, "swap_mb": 0, "is_public": True},
    {"id": "f-gpu",     "name": "gpu.xlarge", "vcpus": 8, "ram_mb": 32768, "disk_gb": 100, "ephemeral_gb": 0, "swap_mb": 0, "is_public": False},
]

DEMO_IMAGES = [
    {"id": "img-ubuntu22",  "name": "Ubuntu 22.04 LTS",    "status": "active", "visibility": "public", "size_bytes": 2361393152, "disk_format": "qcow2"},
    {"id": "img-ubuntu24",  "name": "Ubuntu 24.04 LTS",    "status": "active", "visibility": "public", "size_bytes": 2684354560, "disk_format": "qcow2"},
    {"id": "img-centos9",   "name": "CentOS Stream 9",     "status": "active", "visibility": "public", "size_bytes": 1932735283, "disk_format": "qcow2"},
    {"id": "img-rhel9",     "name": "RHEL 9.2",            "status": "active", "visibility": "public", "size_bytes": 3221225472, "disk_format": "qcow2"},
    {"id": "img-win2022",   "name": "Windows Server 2022", "status": "active", "visibility": "public", "size_bytes": 12884901888,"disk_format": "raw"},
    {"id": "img-rocky9",    "name": "Rocky Linux 9",       "status": "active", "visibility": "public", "size_bytes": 2147483648, "disk_format": "qcow2"},
]

# VM templates: (name_prefix, project_id, flavor_id, hypervisor, image_id)
VM_TEMPLATES = [
    # Acme production – busy workloads
    ("acme-web-01",       "p-acme-prod",    "f-large",  "kvm-node-01", "img-ubuntu22"),
    ("acme-web-02",       "p-acme-prod",    "f-large",  "kvm-node-02", "img-ubuntu22"),
    ("acme-api-01",       "p-acme-prod",    "f-xlarge", "kvm-node-01", "img-ubuntu24"),
    ("acme-api-02",       "p-acme-prod",    "f-xlarge", "kvm-node-02", "img-ubuntu24"),
    ("acme-db-primary",   "p-acme-prod",    "f-db",     "kvm-node-01", "img-centos9"),
    ("acme-db-replica",   "p-acme-prod",    "f-db",     "kvm-node-02", "img-centos9"),
    ("acme-cache-01",     "p-acme-prod",    "f-medium", "kvm-node-03", "img-ubuntu22"),
    ("acme-worker-01",    "p-acme-prod",    "f-medium", "kvm-node-03", "img-ubuntu22"),
    ("acme-worker-02",    "p-acme-prod",    "f-medium", "kvm-node-04", "img-ubuntu22"),
    ("acme-monitor",      "p-acme-prod",    "f-small",  "kvm-node-04", "img-ubuntu24"),
    # Acme staging
    ("acme-stg-web",      "p-acme-staging", "f-medium", "kvm-node-03", "img-ubuntu22"),
    ("acme-stg-api",      "p-acme-staging", "f-medium", "kvm-node-03", "img-ubuntu24"),
    ("acme-stg-db",       "p-acme-staging", "f-medium", "kvm-node-04", "img-centos9"),
    # Acme dev
    ("acme-dev-sandbox",  "p-acme-dev",     "f-small",  "kvm-node-04", "img-ubuntu24"),
    ("acme-dev-ci",       "p-acme-dev",     "f-medium", "kvm-node-04", "img-ubuntu22"),
    # Globex production – enterprise workloads
    ("globex-erp-01",     "p-globex-prod",  "f-2xlarge","kvm-node-01", "img-rhel9"),
    ("globex-erp-02",     "p-globex-prod",  "f-2xlarge","kvm-node-02", "img-rhel9"),
    ("globex-web-01",     "p-globex-prod",  "f-large",  "kvm-node-01", "img-ubuntu22"),
    ("globex-mail",       "p-globex-prod",  "f-medium", "kvm-node-03", "img-centos9"),
    ("globex-ad-dc",      "p-globex-prod",  "f-large",  "kvm-node-02", "img-win2022"),
    ("globex-fileserver",  "p-globex-prod", "f-xlarge", "kvm-node-01", "img-win2022"),
    ("globex-sql-primary", "p-globex-prod", "f-db",     "kvm-node-02", "img-win2022"),
    ("globex-backup-srv",  "p-globex-prod", "f-medium", "kvm-node-04", "img-centos9"),
    # Globex DR
    ("globex-dr-erp",      "p-globex-dr",   "f-xlarge", "kvm-node-05", "img-rhel9"),
    ("globex-dr-db",       "p-globex-dr",   "f-db",     "kvm-node-05", "img-win2022"),
    # Initech production
    ("initech-k8s-master", "p-initech-prod","f-large",  "kvm-node-03", "img-ubuntu24"),
    ("initech-k8s-w1",    "p-initech-prod", "f-xlarge", "kvm-node-03", "img-ubuntu24"),
    ("initech-k8s-w2",    "p-initech-prod", "f-xlarge", "kvm-node-04", "img-ubuntu24"),
    ("initech-k8s-w3",    "p-initech-prod", "f-xlarge", "kvm-node-04", "img-ubuntu24"),
    ("initech-gitlab",    "p-initech-prod", "f-large",  "kvm-node-04", "img-ubuntu22"),
    ("initech-registry",  "p-initech-prod", "f-medium", "kvm-node-04", "img-ubuntu22"),
    ("initech-jenkins",   "p-initech-prod", "f-medium", "kvm-node-03", "img-centos9"),
    # Initech test
    ("initech-test-01",   "p-initech-test", "f-small",  "kvm-node-05", "img-ubuntu24"),
    ("initech-test-02",   "p-initech-test", "f-small",  "kvm-node-05", "img-ubuntu24"),
    ("initech-qa-db",     "p-initech-test", "f-medium", "kvm-node-05", "img-centos9"),
]

DEMO_NETWORKS = [
    {"id": "net-acme-prod",     "name": "acme-production",  "project_id": "p-acme-prod",    "status": "ACTIVE", "admin_state_up": True, "is_shared": False, "is_external": False},
    {"id": "net-acme-staging",  "name": "acme-staging",     "project_id": "p-acme-staging", "status": "ACTIVE", "admin_state_up": True, "is_shared": False, "is_external": False},
    {"id": "net-acme-dev",      "name": "acme-dev",         "project_id": "p-acme-dev",     "status": "ACTIVE", "admin_state_up": True, "is_shared": False, "is_external": False},
    {"id": "net-globex-prod",   "name": "globex-production","project_id": "p-globex-prod",  "status": "ACTIVE", "admin_state_up": True, "is_shared": False, "is_external": False},
    {"id": "net-globex-dr",     "name": "globex-dr",        "project_id": "p-globex-dr",    "status": "ACTIVE", "admin_state_up": True, "is_shared": False, "is_external": False},
    {"id": "net-initech-prod",  "name": "initech-production","project_id": "p-initech-prod","status": "ACTIVE", "admin_state_up": True, "is_shared": False, "is_external": False},
    {"id": "net-initech-test",  "name": "initech-testing",  "project_id": "p-initech-test", "status": "ACTIVE", "admin_state_up": True, "is_shared": False, "is_external": False},
    {"id": "net-external",      "name": "external-network", "project_id": "p-acme-prod",    "status": "ACTIVE", "admin_state_up": True, "is_shared": True,  "is_external": True},
]

DEMO_SUBNETS = [
    {"id": "sub-acme-prod",   "name": "acme-prod-subnet",  "network_id": "net-acme-prod",    "cidr": "10.10.1.0/24",  "gateway_ip": "10.10.1.1",  "enable_dhcp": True},
    {"id": "sub-acme-stg",    "name": "acme-stg-subnet",   "network_id": "net-acme-staging", "cidr": "10.10.2.0/24",  "gateway_ip": "10.10.2.1",  "enable_dhcp": True},
    {"id": "sub-acme-dev",    "name": "acme-dev-subnet",   "network_id": "net-acme-dev",     "cidr": "10.10.3.0/24",  "gateway_ip": "10.10.3.1",  "enable_dhcp": True},
    {"id": "sub-globex-prod", "name": "globex-prod-subnet","network_id": "net-globex-prod",  "cidr": "10.20.1.0/24",  "gateway_ip": "10.20.1.1",  "enable_dhcp": True},
    {"id": "sub-globex-dr",   "name": "globex-dr-subnet",  "network_id": "net-globex-dr",    "cidr": "10.20.2.0/24",  "gateway_ip": "10.20.2.1",  "enable_dhcp": True},
    {"id": "sub-initech-prod","name": "initech-prod-subnet","network_id": "net-initech-prod","cidr": "10.30.1.0/24",  "gateway_ip": "10.30.1.1",  "enable_dhcp": True},
    {"id": "sub-initech-test","name": "initech-test-subnet","network_id": "net-initech-test","cidr": "10.30.2.0/24",  "gateway_ip": "10.30.2.1",  "enable_dhcp": True},
    {"id": "sub-external",    "name": "external-subnet",   "network_id": "net-external",     "cidr": "192.168.100.0/24","gateway_ip": "192.168.100.1","enable_dhcp": False},
]

DEMO_ROUTERS = [
    {"id": "rtr-acme",    "name": "acme-router",    "project_id": "p-acme-prod",   "external_net_id": "net-external"},
    {"id": "rtr-globex",  "name": "globex-router",  "project_id": "p-globex-prod", "external_net_id": "net-external"},
    {"id": "rtr-initech", "name": "initech-router", "project_id": "p-initech-prod","external_net_id": "net-external"},
]

DEMO_ROLES_OS = [
    {"id": "role-admin",   "name": "admin",  "description": "Full administrative access"},
    {"id": "role-member",  "name": "member", "description": "Standard project member"},
    {"id": "role-reader",  "name": "reader", "description": "Read-only access"},
]


# ---------------------------------------------------------------------------
# Seeding functions
# ---------------------------------------------------------------------------
def seed_domains(cur):
    for d in DEMO_DOMAINS:
        cur.execute(
            "INSERT INTO domains (id, name, raw_json, last_seen_at) VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (d["id"], d["name"], json.dumps({"demo": True}), now())
        )
    print(f"  + {len(DEMO_DOMAINS)} domains")


def seed_projects(cur):
    for p in DEMO_PROJECTS:
        cur.execute(
            "INSERT INTO projects (id, name, domain_id, raw_json, last_seen_at) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (p["id"], p["name"], p["domain_id"], json.dumps({"demo": True}), now())
        )
    print(f"  + {len(DEMO_PROJECTS)} projects")


def seed_hypervisors(cur):
    for h in DEMO_HYPERVISORS:
        cur.execute(
            """INSERT INTO hypervisors (id, hostname, hypervisor_type, vcpus, memory_mb, local_gb, state, status, raw_json, last_seen_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
            (h["id"], h["hostname"], h["hypervisor_type"], h["vcpus"], h["memory_mb"],
             h["local_gb"], h["state"], h["status"], json.dumps({"demo": True}), now())
        )
    print(f"  + {len(DEMO_HYPERVISORS)} hypervisors")


def seed_flavors(cur):
    for f in DEMO_FLAVORS:
        cur.execute(
            """INSERT INTO flavors (id, name, vcpus, ram_mb, disk_gb, ephemeral_gb, swap_mb, is_public, raw_json, last_seen_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
            (f["id"], f["name"], f["vcpus"], f["ram_mb"], f["disk_gb"],
             f["ephemeral_gb"], f["swap_mb"], f["is_public"], json.dumps({"demo": True}), now())
        )
    print(f"  + {len(DEMO_FLAVORS)} flavors")


def seed_images(cur):
    for i in DEMO_IMAGES:
        cur.execute(
            """INSERT INTO images (id, name, status, visibility, size_bytes, disk_format, container_format, raw_json, last_seen_at, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
            (i["id"], i["name"], i["status"], i["visibility"], i["size_bytes"],
             i["disk_format"], "bare", json.dumps({"demo": True}), now(), ago(days=90))
        )
    print(f"  + {len(DEMO_IMAGES)} images")


def seed_networks(cur):
    for n in DEMO_NETWORKS:
        cur.execute(
            """INSERT INTO networks (id, name, project_id, status, admin_state_up, is_shared, is_external, raw_json, last_seen_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
            (n["id"], n["name"], n["project_id"], n["status"], n["admin_state_up"],
             n["is_shared"], n["is_external"], json.dumps({"demo": True}), now())
        )
    print(f"  + {len(DEMO_NETWORKS)} networks")


def seed_subnets(cur):
    for s in DEMO_SUBNETS:
        cur.execute(
            """INSERT INTO subnets (id, name, network_id, cidr, gateway_ip, enable_dhcp, raw_json, last_seen_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
            (s["id"], s["name"], s["network_id"], s["cidr"], s["gateway_ip"],
             s["enable_dhcp"], json.dumps({"demo": True}), now())
        )
    print(f"  + {len(DEMO_SUBNETS)} subnets")


def seed_routers(cur):
    for r in DEMO_ROUTERS:
        cur.execute(
            """INSERT INTO routers (id, name, project_id, external_net_id, raw_json, last_seen_at)
               VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
            (r["id"], r["name"], r["project_id"], r["external_net_id"], json.dumps({"demo": True}), now())
        )
    print(f"  + {len(DEMO_ROUTERS)} routers")


def seed_roles(cur):
    for r in DEMO_ROLES_OS:
        cur.execute(
            "INSERT INTO roles (id, name, description, raw_json, last_seen_at) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
            (r["id"], r["name"], r["description"], json.dumps({"demo": True}), now())
        )
    print(f"  + {len(DEMO_ROLES_OS)} roles")


def seed_users(cur):
    """Create demo OpenStack users with role assignments."""
    demo_users = [
        {"id": "u-alice",   "name": "alice@acme-corp.com",    "email": "alice@acme-corp.com",   "domain_id": "d-acme-corp",  "default_project_id": "p-acme-prod"},
        {"id": "u-bob",     "name": "bob@acme-corp.com",      "email": "bob@acme-corp.com",     "domain_id": "d-acme-corp",  "default_project_id": "p-acme-staging"},
        {"id": "u-charlie", "name": "charlie@globex-inc.com", "email": "charlie@globex-inc.com","domain_id": "d-globex-inc", "default_project_id": "p-globex-prod"},
        {"id": "u-diana",   "name": "diana@globex-inc.com",   "email": "diana@globex-inc.com",  "domain_id": "d-globex-inc", "default_project_id": "p-globex-prod"},
        {"id": "u-evan",    "name": "evan@initech.io",        "email": "evan@initech.io",       "domain_id": "d-initech",    "default_project_id": "p-initech-prod"},
        {"id": "u-fiona",   "name": "fiona@initech.io",       "email": "fiona@initech.io",      "domain_id": "d-initech",    "default_project_id": "p-initech-test"},
        {"id": "u-svc",     "name": "svc-snapshot@demo.local","email": "svc@demo.local",        "domain_id": "d-acme-corp",  "default_project_id": "p-acme-prod"},
    ]
    for u in demo_users:
        cur.execute(
            """INSERT INTO users (id, name, email, enabled, domain_id, default_project_id, raw_json, last_seen_at, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
            (u["id"], u["name"], u["email"], True, u["domain_id"],
             u["default_project_id"], json.dumps({"demo": True}), now(), ago(days=60))
        )

    # Role assignments - each user gets 'member' on their default project, alice & charlie get 'admin' too
    assignments = [
        ("role-admin",  "u-alice",   "p-acme-prod",    "d-acme-corp"),
        ("role-member", "u-alice",   "p-acme-prod",    "d-acme-corp"),
        ("role-member", "u-bob",     "p-acme-staging", "d-acme-corp"),
        ("role-member", "u-bob",     "p-acme-dev",     "d-acme-corp"),
        ("role-admin",  "u-charlie", "p-globex-prod",  "d-globex-inc"),
        ("role-member", "u-charlie", "p-globex-prod",  "d-globex-inc"),
        ("role-member", "u-diana",   "p-globex-dr",    "d-globex-inc"),
        ("role-admin",  "u-evan",    "p-initech-prod", "d-initech"),
        ("role-member", "u-evan",    "p-initech-prod", "d-initech"),
        ("role-member", "u-fiona",   "p-initech-test", "d-initech"),
    ]
    for role_id, user_id, project_id, domain_id in assignments:
        cur.execute(
            """INSERT INTO role_assignments (role_id, user_id, project_id, domain_id, raw_json, last_seen_at)
               VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
            (role_id, user_id, project_id, domain_id, json.dumps({"demo": True}), now())
        )
    print(f"  + {len(demo_users)} users, {len(assignments)} role assignments")


def seed_servers_and_volumes(cur):
    """Create VMs with attached volumes and some snapshots."""
    flavor_map = {f["id"]: f for f in DEMO_FLAVORS}
    project_domain = {}
    for p in DEMO_PROJECTS:
        for d in DEMO_DOMAINS:
            if d["id"] == p["domain_id"]:
                project_domain[p["id"]] = (p["name"], d["name"], d["id"])

    servers = []
    volumes = []
    snapshots = []
    security_groups = []
    sg_rules = []

    # Create a default security group per project
    for p in DEMO_PROJECTS:
        sg_id = f"sg-default-{p['id']}"
        pname, dname, did = project_domain.get(p["id"], (p["name"], "unknown", ""))
        security_groups.append({
            "id": sg_id, "name": "default", "description": "Default security group",
            "project_id": p["id"], "project_name": pname, "tenant_name": pname,
            "domain_id": did, "domain_name": dname,
        })
        # Allow SSH + HTTPS
        for proto, port in [("tcp", 22), ("tcp", 443), ("tcp", 80), ("icmp", None)]:
            sg_rules.append({
                "id": uid(), "security_group_id": sg_id, "direction": "ingress",
                "ethertype": "IPv4", "protocol": proto,
                "port_range_min": port, "port_range_max": port,
                "remote_ip_prefix": "0.0.0.0/0", "project_id": p["id"],
            })

    random.seed(42)  # Reproducible randomness

    for i, (name, project_id, flavor_id, hyp, image_id) in enumerate(VM_TEMPLATES):
        server_id = f"srv-{name}"
        flavor = flavor_map[flavor_id]
        created = ago(days=random.randint(7, 180))

        # Determine status — most are ACTIVE, a few SHUTOFF
        statuses = ["ACTIVE"] * 8 + ["SHUTOFF"] * 2
        vm_status = random.choice(statuses)

        servers.append({
            "id": server_id, "name": name, "project_id": project_id,
            "status": vm_status, "vm_state": "active" if vm_status == "ACTIVE" else "stopped",
            "flavor_id": flavor_id, "hypervisor_hostname": hyp, "created_at": created,
        })

        # Each server gets 1-2 volumes
        vol_sizes = [flavor["disk_gb"]]
        if "db" in name or "erp" in name or "fileserver" in name:
            vol_sizes.append(random.choice([100, 200, 500]))

        for vi, size in enumerate(vol_sizes):
            vol_id = f"vol-{name}-{vi}"
            volumes.append({
                "id": vol_id, "name": f"{name}-vol-{vi}",
                "project_id": project_id, "size_gb": size,
                "status": "in-use", "volume_type": "ceph-ssd",
                "server_id": server_id, "bootable": vi == 0, "created_at": created,
            })

            # Snapshots: most volumes get 1-3 recent snapshots
            pname, dname, did = project_domain.get(project_id, ("", "", ""))
            num_snaps = random.choices([0, 1, 2, 3], weights=[1, 3, 4, 2])[0]
            for si in range(num_snaps):
                snap_age = random.randint(0, 14)
                snap_time = ago(days=snap_age, hours=random.randint(0, 23))
                snapshots.append({
                    "id": uid(), "name": f"snap-{name}-{vi}-{si}",
                    "description": f"Automated snapshot for {name}",
                    "project_id": project_id, "project_name": pname,
                    "tenant_name": pname, "domain_name": dname, "domain_id": did,
                    "volume_id": vol_id, "size_gb": size,
                    "status": "available", "created_at": snap_time,
                })

    # Insert servers
    for s in servers:
        cur.execute(
            """INSERT INTO servers (id, name, project_id, status, vm_state, flavor_id, hypervisor_hostname, created_at, raw_json, last_seen_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
            (s["id"], s["name"], s["project_id"], s["status"], s["vm_state"],
             s["flavor_id"], s["hypervisor_hostname"], s["created_at"],
             json.dumps({"demo": True, "image": {"id": VM_TEMPLATES[[t[0] for t in VM_TEMPLATES].index(s["name"])][4]}}), now())
        )

    # Insert volumes
    for v in volumes:
        cur.execute(
            """INSERT INTO volumes (id, name, project_id, size_gb, status, volume_type, server_id, bootable, created_at, raw_json, last_seen_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
            (v["id"], v["name"], v["project_id"], v["size_gb"], v["status"],
             v["volume_type"], v["server_id"], v["bootable"], v["created_at"],
             json.dumps({"demo": True}), now())
        )

    # Insert snapshots
    for snap in snapshots:
        cur.execute(
            """INSERT INTO snapshots (id, name, description, project_id, project_name, tenant_name, domain_name, domain_id, volume_id, size_gb, status, created_at, raw_json, last_seen_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
            (snap["id"], snap["name"], snap["description"], snap["project_id"],
             snap["project_name"], snap["tenant_name"], snap["domain_name"],
             snap["domain_id"], snap["volume_id"], snap["size_gb"],
             snap["status"], snap["created_at"], json.dumps({"demo": True}), now())
        )

    # Insert security groups
    for sg in security_groups:
        cur.execute(
            """INSERT INTO security_groups (id, name, description, project_id, project_name, tenant_name, domain_id, domain_name, raw_json, last_seen_at, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
            (sg["id"], sg["name"], sg["description"], sg["project_id"],
             sg["project_name"], sg["tenant_name"], sg["domain_id"],
             sg["domain_name"], json.dumps({"demo": True}), now(), ago(days=90))
        )

    for rule in sg_rules:
        cur.execute(
            """INSERT INTO security_group_rules (id, security_group_id, direction, ethertype, protocol, port_range_min, port_range_max, remote_ip_prefix, project_id, raw_json, last_seen_at, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
            (rule["id"], rule["security_group_id"], rule["direction"],
             rule["ethertype"], rule["protocol"], rule["port_range_min"],
             rule["port_range_max"], rule["remote_ip_prefix"], rule["project_id"],
             json.dumps({"demo": True}), now(), ago(days=90))
        )

    print(f"  + {len(servers)} servers, {len(volumes)} volumes, {len(snapshots)} snapshots")
    print(f"  + {len(security_groups)} security groups, {len(sg_rules)} rules")
    return servers, volumes, snapshots


def seed_inventory_run(cur):
    """Record a completed inventory run."""
    cur.execute(
        """INSERT INTO inventory_runs (started_at, finished_at, created_at, status, source, host_name, duration_seconds, notes)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (ago(minutes=5), now(), now(), "completed", "demo_seed", "demo-host", 12, "Initial demo data seeding")
    )
    print("  + 1 inventory run")


def seed_snapshot_policies(cur, volumes):
    """Create snapshot policy sets and assign volumes."""
    policies = [
        {
            "id": None, "name": "Daily Production",
            "description": "Daily snapshots with 14-day retention for production workloads",
            "is_global": False, "tenant_id": "p-acme-prod", "tenant_name": "production",
            "policies": json.dumps([{"name": "daily", "interval_hours": 24, "time_of_day": "02:00"}]),
            "retention_map": json.dumps({"daily": 14}),
            "priority": 10, "is_active": True,
        },
        {
            "id": None, "name": "Weekly Non-Prod",
            "description": "Weekly snapshots with 30-day retention for staging/dev",
            "is_global": True, "tenant_id": None, "tenant_name": None,
            "policies": json.dumps([{"name": "weekly", "interval_hours": 168, "time_of_day": "03:00"}]),
            "retention_map": json.dumps({"weekly": 4}),
            "priority": 0, "is_active": True,
        },
    ]
    policy_ids = []
    for pol in policies:
        cur.execute(
            """INSERT INTO snapshot_policy_sets (name, description, is_global, tenant_id, tenant_name, policies, retention_map, priority, is_active, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT DO NOTHING RETURNING id""",
            (pol["name"], pol["description"], pol["is_global"], pol["tenant_id"],
             pol["tenant_name"], pol["policies"], pol["retention_map"],
             pol["priority"], pol["is_active"], "demo_seed")
        )
        row = cur.fetchone()
        policy_ids.append(row[0] if row else None)

    # Assign production volumes to the daily policy
    assigned = 0
    for v in volumes:
        if "prod" in v["project_id"]:
            pid = policy_ids[0]
        else:
            pid = policy_ids[1]
        if pid is None:
            continue
        # Find project/domain info
        proj = next((p for p in DEMO_PROJECTS if p["id"] == v["project_id"]), None)
        dom = next((d for d in DEMO_DOMAINS if d["id"] == (proj["domain_id"] if proj else "")), None)
        cur.execute(
            """INSERT INTO snapshot_assignments (volume_id, volume_name, tenant_id, tenant_name, project_id, project_name, policy_set_id, auto_snapshot, policies, retention_map, assignment_source, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (volume_id) DO NOTHING""",
            (v["id"], v["name"], dom["id"] if dom else "", dom["name"] if dom else "",
             v["project_id"], proj["name"] if proj else "", pid, True,
             '[]', '{}', "auto", "demo_seed")
        )
        assigned += 1

    print(f"  + {len(policies)} snapshot policies, {assigned} volume assignments")


def seed_compliance(cur, volumes, snapshots):
    """Create a compliance report."""
    cur.execute(
        """INSERT INTO compliance_reports (report_date, input_file, output_file, sla_days, total_volumes, compliant_count, noncompliant_count)
           VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (now(), "demo_seed", "demo_report.csv", 2, len(volumes),
         int(len(volumes) * 0.82), int(len(volumes) * 0.18))
    )
    report_id = cur.fetchone()[0]

    # Determine compliance per volume
    vol_snaps = {}
    for s in snapshots:
        if s["volume_id"] not in vol_snaps or s["created_at"] > vol_snaps[s["volume_id"]]:
            vol_snaps[s["volume_id"]] = s["created_at"]

    for v in volumes:
        last_snap = vol_snaps.get(v["id"])
        proj = next((p for p in DEMO_PROJECTS if p["id"] == v["project_id"]), None)
        dom = next((d for d in DEMO_DOMAINS if d["id"] == (proj["domain_id"] if proj else "")), None)

        if last_snap:
            days_since = (now() - last_snap).total_seconds() / 86400
        else:
            days_since = 999

        is_compliant = days_since <= 2

        cur.execute(
            """INSERT INTO compliance_details (report_id, volume_id, volume_name, tenant_id, tenant_name, project_id, project_name, domain_id, domain_name, last_snapshot_at, days_since_snapshot, is_compliant, compliance_status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (report_id, v["id"], v["name"],
             dom["id"] if dom else "", dom["name"] if dom else "",
             v["project_id"], proj["name"] if proj else "",
             dom["id"] if dom else "", dom["name"] if dom else "",
             last_snap, round(days_since, 1), is_compliant,
             "compliant" if is_compliant else "non-compliant")
        )

    print(f"  + 1 compliance report with {len(volumes)} details")


def seed_drift(cur):
    """Create drift rules and some events."""
    rules = [
        {"resource_type": "server",  "field_name": "status",            "severity": "critical", "description": "VM status changed"},
        {"resource_type": "server",  "field_name": "hypervisor_hostname","severity": "warning",  "description": "VM migrated to different host"},
        {"resource_type": "volume",  "field_name": "status",            "severity": "warning",  "description": "Volume status changed"},
        {"resource_type": "network", "field_name": "admin_state_up",    "severity": "critical", "description": "Network admin state changed"},
    ]
    rule_ids = []
    for r in rules:
        cur.execute(
            """INSERT INTO drift_rules (resource_type, field_name, severity, description, enabled)
               VALUES (%s,%s,%s,%s,%s) ON CONFLICT (resource_type, field_name) DO NOTHING RETURNING id""",
            (r["resource_type"], r["field_name"], r["severity"], r["description"], True)
        )
        row = cur.fetchone()
        rule_ids.append(row[0] if row else None)

    # A few demo drift events
    events = [
        (rule_ids[0], "server", "srv-acme-worker-01", "acme-worker-01", "p-acme-prod", "production", "d-acme-corp", "acme-corp.com", "critical", "status", "ACTIVE", "SHUTOFF", "VM unexpectedly stopped", ago(hours=3)),
        (rule_ids[1], "server", "srv-globex-erp-01", "globex-erp-01", "p-globex-prod", "production", "d-globex-inc", "globex-inc.com", "warning", "hypervisor_hostname", "kvm-node-01", "kvm-node-02", "VM live-migrated", ago(hours=8)),
        (rule_ids[2], "volume", "vol-acme-db-primary-1", "acme-db-primary-vol-1", "p-acme-prod", "production", "d-acme-corp", "acme-corp.com", "warning", "status", "in-use", "error", "Volume entered error state", ago(hours=1)),
    ]
    inserted = 0
    for ev in events:
        if ev[0] is not None:
            cur.execute(
                """INSERT INTO drift_events (rule_id, resource_type, resource_id, resource_name, project_id, project_name, domain_id, domain_name, severity, field_changed, old_value, new_value, description, detected_at, acknowledged)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (*ev, False)
            )
            inserted += 1

    print(f"  + {len(rules)} drift rules, {inserted} drift events")


def seed_activity_log(cur):
    """Seed recent activity log entries."""
    activities = [
        (ago(minutes=10), "alice@acme-corp.com",   "created",  "snapshot", None, "snap-acme-web-01-0-0",    "d-acme-corp", "acme-corp.com",   {}, "success"),
        (ago(minutes=30), "svc-snapshot@demo.local","created", "snapshot", None, "snap-globex-erp-01-0-0",  "d-globex-inc","globex-inc.com",  {}, "success"),
        (ago(hours=1),    "charlie@globex-inc.com", "updated", "server",   "srv-globex-mail", "globex-mail","d-globex-inc","globex-inc.com",  {"field": "status", "old": "SHUTOFF", "new": "ACTIVE"}, "success"),
        (ago(hours=2),    "evan@initech.io",        "created", "server",   "srv-initech-test-02", "initech-test-02", "d-initech", "initech.io", {}, "success"),
        (ago(hours=3),    "admin",                  "deleted", "snapshot", None, "snap-old-cleanup",        "d-acme-corp", "acme-corp.com",   {}, "success"),
        (ago(hours=5),    "system",                 "created", "compliance_report", None, "Weekly Compliance","d-acme-corp","acme-corp.com",  {}, "success"),
        (ago(hours=8),    "bob@acme-corp.com",      "created", "volume",   "vol-acme-stg-web-0", "acme-stg-web-vol-0", "d-acme-corp", "acme-corp.com", {"size_gb": 40}, "success"),
        (ago(hours=12),   "diana@globex-inc.com",   "updated", "network",  "net-globex-prod", "globex-production", "d-globex-inc", "globex-inc.com", {}, "success"),
        (ago(days=1),     "fiona@initech.io",       "created", "server",   "srv-initech-test-01", "initech-test-01", "d-initech", "initech.io", {}, "success"),
        (ago(days=1, hours=3), "admin",             "executed","runbook",  None, "Quota Threshold Check",   None, None, {"dry_run": True, "items_found": 2}, "success"),
    ]
    for ts, actor, action, rtype, rid, rname, did, dname, details, result in activities:
        cur.execute(
            """INSERT INTO activity_log (timestamp, actor, action, resource_type, resource_id, resource_name, domain_id, domain_name, details, result)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (ts, actor, action, rtype, rid, rname, did, dname, json.dumps(details), result)
        )
    print(f"  + {len(activities)} activity log entries")


def seed_metering_config(cur):
    """Seed metering configuration and flavor pricing."""
    cur.execute(
        """INSERT INTO metering_config (id, enabled, collection_interval_min, retention_days,
           cost_per_vcpu_hour, cost_per_gb_ram_hour, cost_per_gb_storage_month, cost_per_snapshot_gb_month, cost_currency)
           VALUES (1, true, 15, 90, 0.025, 0.005, 0.10, 0.05, 'USD')
           ON CONFLICT (id) DO NOTHING"""
    )
    for f in DEMO_FLAVORS:
        hourly = round(f["vcpus"] * 0.025 + (f["ram_mb"] / 1024) * 0.005 + f["disk_gb"] * 0.0001, 4)
        cur.execute(
            """INSERT INTO metering_flavor_pricing (flavor_name, vcpus, ram_gb, disk_gb, cost_per_hour, currency)
               VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (flavor_name) DO NOTHING""",
            (f["name"], f["vcpus"], f["ram_mb"] / 1024, f["disk_gb"], hourly, "USD")
        )
    print(f"  + metering config + {len(DEMO_FLAVORS)} flavor prices")


def seed_backup_config(cur):
    """Seed backup configuration."""
    cur.execute(
        """INSERT INTO backup_config (id, enabled, nfs_path, schedule_type, schedule_time_utc, retention_count, retention_days)
           VALUES (1, true, '/backups', 'daily', '02:00', 7, 30)
           ON CONFLICT (id) DO NOTHING"""
    )
    print("  + backup config")


def seed_runbooks(cur):
    """Seed the 5 built-in runbooks and their approval policies."""
    runbooks = [
        ("stuck_vm_remediation", "Stuck VM Remediation",       "Detect and remediate VMs stuck in ERROR/BUILD state",         "operations",  "medium"),
        ("orphan_resource_cleanup","Orphan Resource Cleanup",  "Find and clean up orphaned ports, volumes, floating IPs",     "housekeeping","low"),
        ("security_group_audit",  "Security Group Audit",      "Identify overly permissive security group rules",             "security",    "low"),
        ("quota_threshold_check", "Quota Threshold Check",     "Alert on projects approaching quota limits",                  "capacity",    "low"),
        ("diagnostics_bundle",    "Diagnostics Bundle",        "Collect hypervisors, services, resources, and quota summary", "troubleshoot","low"),
    ]
    for name, display, desc, cat, risk in runbooks:
        cur.execute(
            """INSERT INTO runbooks (runbook_id, name, display_name, description, category, risk_level, supports_dry_run, enabled, parameters_schema)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (name) DO NOTHING""",
            (uid(), name, display, desc, cat, risk, True, True, json.dumps({}))
        )
        # Default approval policy
        cur.execute(
            """INSERT INTO runbook_approval_policies (policy_id, runbook_name, trigger_role, approver_role, approval_mode, enabled)
               VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
            (uid(), name, "operator", "admin", "single_approval", True)
        )
    print(f"  + {len(runbooks)} runbooks with approval policies")


# ---------------------------------------------------------------------------
# Demo metrics cache (static file for host/VM metrics when no PF9 is connected)
# ---------------------------------------------------------------------------
def generate_demo_metrics_cache():
    """Generate a realistic metrics_cache.json for demo mode."""
    flavor_map = {f["id"]: f for f in DEMO_FLAVORS}
    project_domain = {}
    for p in DEMO_PROJECTS:
        for d in DEMO_DOMAINS:
            if d["id"] == p["domain_id"]:
                project_domain[p["id"]] = (p["name"], d["name"])

    random.seed(42)

    hosts = []
    for h in DEMO_HYPERVISORS:
        cpu = round(random.uniform(5, 85) if h["state"] == "up" else 0, 1)
        ram_used = int(h["memory_mb"] * random.uniform(0.3, 0.8))
        disk_total = h["local_gb"]
        disk_used = int(disk_total * random.uniform(0.15, 0.65))
        hosts.append({
            "hostname": h["hostname"],
            "ip": f"10.0.1.{10 + DEMO_HYPERVISORS.index(h)}",
            "cpu_usage_percent": cpu,
            "memory_usage_mb": ram_used,
            "memory_total_mb": h["memory_mb"],
            "memory_usage_percent": round(ram_used / h["memory_mb"] * 100, 1),
            "disk_total_gb": disk_total,
            "disk_used_gb": disk_used,
            "disk_usage_percent": round(disk_used / disk_total * 100, 1),
            "network_rx_mb": random.randint(1000, 500000),
            "network_tx_mb": random.randint(500, 200000),
            "storage_usage_percent": round(disk_used / disk_total * 100, 1),
            "disk_available_gb": disk_total - disk_used,
            "timestamp": now().isoformat(),
        })

    vms = []
    for name, project_id, flavor_id, hyp, image_id in VM_TEMPLATES:
        flavor = flavor_map[flavor_id]
        pname, dname = project_domain.get(project_id, ("", ""))
        cpu = round(random.uniform(0.5, 45), 1)
        if "db" in name or "erp" in name:
            cpu = round(random.uniform(15, 75), 1)
        elif "worker" in name or "jenkins" in name:
            cpu = round(random.uniform(10, 55), 1)

        mem_total = flavor["ram_mb"]
        mem_used = int(mem_total * random.uniform(0.3, 0.85))
        disk_total = flavor["disk_gb"]
        disk_used = round(disk_total * random.uniform(0.1, 0.7), 1)

        ip_suffix = VM_TEMPLATES.index((name, project_id, flavor_id, hyp, image_id)) + 10
        subnet_base = "10.10.1" if "acme" in project_id else ("10.20.1" if "globex" in project_id else "10.30.1")

        vms.append({
            "vm_id": f"srv-{name}",
            "vm_name": name,
            "vm_ip": f"{subnet_base}.{ip_suffix}",
            "project_name": pname,
            "domain": dname,
            "user_name": f"user@{dname}",
            "flavor": flavor["name"],
            "host": hyp,
            "timestamp": now().isoformat(),
            "cpu_usage_percent": cpu,
            "memory_usage_mb": mem_used,
            "memory_total_mb": mem_total,
            "memory_usage_percent": round(mem_used / mem_total * 100, 1),
            "network_rx_bytes": random.randint(10000, 50000000),
            "network_tx_bytes": random.randint(10000, 50000000),
            "storage_read_bytes": random.randint(100000, 500000000),
            "storage_write_bytes": random.randint(100000, 500000000),
            "storage_total_gb": disk_total,
            "storage_used_gb": disk_used,
            "storage_usage_percent": round(disk_used / disk_total * 100, 1),
        })

    cache = {
        "vms": vms,
        "hosts": hosts,
        "last_update": now().isoformat(),
        "collection_metadata": {
            "source": "demo_seed",
            "demo_mode": True,
            "hosts_count": len(hosts),
            "vms_count": len(vms),
            "timestamp": now().isoformat(),
        }
    }
    return cache


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Seed demo data for PF9 Management Portal")
    parser.add_argument("--db-host", default=os.getenv("PF9_DB_HOST", "localhost"))
    parser.add_argument("--db-port", default=os.getenv("PF9_DB_PORT", "5432"))
    parser.add_argument("--db-name", default=os.getenv("PF9_DB_NAME", os.getenv("POSTGRES_DB", "pf9_mgmt")))
    parser.add_argument("--db-user", default=os.getenv("PF9_DB_USER", os.getenv("POSTGRES_USER", "pf9")))
    parser.add_argument("--db-pass", default=os.getenv("PF9_DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", "")))
    parser.add_argument("--metrics-only", action="store_true", help="Only generate metrics cache, skip DB seeding")
    parser.add_argument("--skip-metrics", action="store_true", help="Skip metrics cache generation")
    args = parser.parse_args()

    # --- Generate demo metrics cache ---
    if not args.skip_metrics:
        cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitoring", "cache")
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, "metrics_cache.json")

        print("=== Generating Demo Metrics Cache ===")
        cache = generate_demo_metrics_cache()
        with open(cache_file, "w") as f:
            json.dump(cache, f, indent=2, default=str)
        print(f"  + Written to {cache_file}")
        print(f"  + {len(cache['hosts'])} hosts, {len(cache['vms'])} VMs")

    if args.metrics_only:
        print("\n=== Demo Metrics Cache Complete ===")
        return

    # --- Connect to database ---
    print(f"\n=== Seeding Demo Data into PostgreSQL ===")
    print(f"  Connecting to {args.db_host}:{args.db_port}/{args.db_name} as {args.db_user}...")

    try:
        conn = psycopg2.connect(
            host=args.db_host,
            port=int(args.db_port),
            dbname=args.db_name,
            user=args.db_user,
            password=args.db_pass,
        )
        conn.autocommit = False
        cur = conn.cursor()
    except Exception as e:
        print(f"  ERROR: Could not connect to database: {e}")
        print(f"  Make sure PostgreSQL is running and credentials are correct.")
        sys.exit(1)

    try:
        print("\n--- Core Infrastructure ---")
        seed_domains(cur)
        seed_projects(cur)
        seed_hypervisors(cur)
        seed_flavors(cur)
        seed_images(cur)
        seed_networks(cur)
        seed_subnets(cur)
        seed_routers(cur)

        print("\n--- Users & RBAC ---")
        seed_roles(cur)
        seed_users(cur)

        print("\n--- Servers, Volumes, Snapshots ---")
        servers, volumes, snapshots = seed_servers_and_volumes(cur)

        print("\n--- Inventory ---")
        seed_inventory_run(cur)

        print("\n--- Snapshot Policies & Compliance ---")
        seed_snapshot_policies(cur, volumes)
        seed_compliance(cur, volumes, snapshots)

        print("\n--- Drift Detection ---")
        seed_drift(cur)

        print("\n--- Activity Log ---")
        seed_activity_log(cur)

        print("\n--- Metering & Billing ---")
        seed_metering_config(cur)

        print("\n--- Backup Config ---")
        seed_backup_config(cur)

        print("\n--- Runbooks ---")
        seed_runbooks(cur)

        conn.commit()
        print("\n=== Demo Data Seeded Successfully ===")
        print(f"  Total: {len(DEMO_DOMAINS)} domains, {len(DEMO_PROJECTS)} projects, {len(VM_TEMPLATES)} VMs")
        print(f"  {len(volumes)} volumes, {len(snapshots)} snapshots")
        print(f"  Ready for demo mode!")

    except Exception as e:
        conn.rollback()
        print(f"\n  ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
