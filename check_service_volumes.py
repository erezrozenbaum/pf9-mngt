#!/usr/bin/env python3
"""Quick script to check service tenant volumes"""
import sys
sys.path.insert(0, '.')
from p9_common import CFG, get_session_best_scope, cinder_volumes_all

session, token = get_session_best_scope()

# Get admin project ID from token
import requests
headers = {"X-Auth-Token": token}
resp = requests.get(f"{CFG['KEYSTONE_URL']}/auth/tokens", headers={"X-Auth-Token": token, "X-Subject-Token": token}, timeout=30)
scoped_project = resp.json()["token"]["project"]
admin_project_id = scoped_project["id"]
admin_project_name = scoped_project["name"]

volumes = cinder_list_all_volumes(session, admin_project_id)
service_vols = [v for v in volumes if v.get('os-vol-tenant-attr:tenant_id') == admin_project_id]

print(f"\nService tenant ({admin_project_id}) has {len(service_vols)} volumes:\n")

for v in service_vols:
    metadata = v.get('metadata', {})
    print(f"Volume: {v['id']}")
    print(f"  Name: {v.get('name', 'unnamed')}")
    print(f"  auto_snapshot: {metadata.get('auto_snapshot', 'NOT SET')}")
    print(f"  policies: {metadata.get('policies', 'NOT SET')}")
    print(f"  Size: {v.get('size')} GB")
    print(f"  Bootable: {v.get('bootable')}")
    print()
