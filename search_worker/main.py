"""
PF9 Search Indexer Worker
=========================
Background worker that incrementally indexes all resource tables
into the unified search_documents table for full-text search
and trigram similarity.

Runs on a configurable interval (default: 5 minutes).
Each doc_type is indexed independently with its own watermark
tracked in search_indexer_state.
"""

import json
import logging
import os
import signal
import time
from datetime import datetime, timezone
from typing import Optional

import psycopg2
import psycopg2.extras

# ── Configuration ────────────────────────────────────────────

DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "pf9_mgmt")
DB_USER = os.getenv("DB_USER", "pf9")
DB_PASS = os.getenv("DB_PASS", "pf9pass")
INDEX_INTERVAL = int(os.getenv("SEARCH_INDEX_INTERVAL", "300"))  # seconds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("search-indexer")

_shutdown = False


def _handle_signal(signum, _frame):
    global _shutdown
    log.info("Received signal %s – shutting down gracefully", signum)
    _shutdown = True


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


def get_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS,
    )


# ── Document builder helpers ────────────────────────────────

def _json_extract(raw_json: Optional[str], *keys) -> str:
    """Safely extract values from a raw_json string/dict."""
    if not raw_json:
        return ""
    try:
        data = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
    except (json.JSONDecodeError, TypeError):
        return ""
    parts = []
    for k in keys:
        val = data.get(k, "")
        if val:
            parts.append(str(val))
    return " ".join(parts)


def _safe(val) -> str:
    """Convert any value to string safely."""
    if val is None:
        return ""
    return str(val)


def _metadata(row: dict, *extra_keys) -> dict:
    """Build a metadata dict from common + extra keys."""
    m = {}
    for k in ("status", "vm_state", "hypervisor_hostname", "flavor_id",
              "size_gb", "severity", "action", "run_type",
              "backup_type", "mode", "protocol"):
        if k in row and row[k] is not None:
            m[k] = row[k]
    for k in extra_keys:
        if k in row and row[k] is not None:
            m[k] = row[k]
    return m


# ── Indexer definitions ────────────────────────────────────
# Each entry: (doc_type, query, row_to_doc_fn)
# The query MUST:
#   - Accept one %s parameter for the last_indexed_at watermark
#   - ORDER BY the timestamp column
#   - Return all columns needed by the row_to_doc_fn

def _build_indexers():
    """Return list of (doc_type, sql, row_to_doc_fn) tuples."""
    indexers = []

    # ── VMs ──────────────────────────────────────────────────
    indexers.append(("vm", """
        SELECT s.id, s.name, s.project_id, p.name AS project_name,
               d.name AS domain_name, d.id AS domain_id,
               s.status, s.vm_state, s.hypervisor_hostname, s.flavor_id,
               s.created_at, s.last_seen_at, s.raw_json,
               f.name AS flavor_name, f.vcpus, f.ram_mb, f.disk_gb,
               (SELECT COUNT(*) FROM volumes v
                JOIN LATERAL (SELECT jsonb_array_elements(
                    CASE WHEN v.raw_json IS NOT NULL
                         THEN (v.raw_json::jsonb -> 'attachments')
                         ELSE '[]'::jsonb END
                ) AS att) x ON TRUE
                WHERE x.att->>'server_id' = s.id) AS attached_volumes
        FROM servers s
        LEFT JOIN projects p ON s.project_id = p.id
        LEFT JOIN domains d ON p.domain_id = d.id
        LEFT JOIN flavors f ON s.flavor_id = f.id
        WHERE s.last_seen_at > %s
        ORDER BY s.last_seen_at
    """, lambda r: {
        "resource_id": r["id"],
        "resource_name": r["name"],
        "tenant_id": r["project_id"],
        "tenant_name": _safe(r.get("project_name")),
        "domain_id": _safe(r.get("domain_id")),
        "domain_name": _safe(r.get("domain_name")),
        "title": f"VM: {r['name']} ({_safe(r.get('status'))})",
        "body_text": " | ".join(filter(None, [
            f"VM {r['name']} is {_safe(r.get('status'))} (state: {_safe(r.get('vm_state'))})",
            f"Running on hypervisor {_safe(r.get('hypervisor_hostname'))}" if r.get("hypervisor_hostname") else None,
            f"Flavor: {_safe(r.get('flavor_name'))} ({r.get('vcpus', '?')} vCPU, {r.get('ram_mb', '?')}MB RAM, {r.get('disk_gb', '?')}GB disk)" if r.get("flavor_name") else None,
            f"Project: {_safe(r.get('project_name'))}, Domain: {_safe(r.get('domain_name'))}",
            f"Created: {r.get('created_at')}" if r.get("created_at") else None,
            _json_extract(r.get("raw_json"), "accessIPv4", "accessIPv6", "key_name"),
        ])),
        "ts": r.get("last_seen_at") or r.get("created_at"),
        "metadata": {
            "status": _safe(r.get("status")),
            "vm_state": _safe(r.get("vm_state")),
            "hypervisor": _safe(r.get("hypervisor_hostname")),
            "flavor": _safe(r.get("flavor_name")),
            "vcpus": r.get("vcpus"),
            "ram_mb": r.get("ram_mb"),
            "disk_gb": r.get("disk_gb"),
            "project": _safe(r.get("project_name")),
            "domain": _safe(r.get("domain_name")),
        },
    }))

    # ── Volumes ──────────────────────────────────────────────
    indexers.append(("volume", """
        SELECT v.id, v.name, v.project_id, p.name AS project_name,
               d.name AS domain_name, d.id AS domain_id,
               v.status, v.volume_type, v.size_gb, v.bootable,
               v.created_at, v.last_seen_at
        FROM volumes v
        LEFT JOIN projects p ON v.project_id = p.id
        LEFT JOIN domains d ON p.domain_id = d.id
        WHERE v.last_seen_at > %s
        ORDER BY v.last_seen_at
    """, lambda r: {
        "resource_id": r["id"],
        "resource_name": _safe(r.get("name")),
        "tenant_id": r.get("project_id"),
        "tenant_name": _safe(r.get("project_name")),
        "domain_id": _safe(r.get("domain_id")),
        "domain_name": _safe(r.get("domain_name")),
        "title": f"Volume: {_safe(r.get('name'))} ({_safe(r.get('status'))}, {_safe(r.get('size_gb'))}GB)",
        "body_text": " | ".join(filter(None, [
            f"Volume {_safe(r.get('name'))} is {_safe(r.get('status'))} ({r.get('size_gb', 0)} GB)",
            f"Type: {_safe(r.get('volume_type'))}" if r.get("volume_type") else None,
            "Bootable volume" if r.get("bootable") else None,
            f"Project: {_safe(r.get('project_name'))}, Domain: {_safe(r.get('domain_name'))}",
        ])),
        "ts": r.get("last_seen_at") or r.get("created_at"),
        "metadata": {
            "status": _safe(r.get("status")),
            "size_gb": r.get("size_gb"),
            "volume_type": _safe(r.get("volume_type")),
            "bootable": r.get("bootable"),
            "project": _safe(r.get("project_name")),
        },
    }))

    # ── Snapshots ────────────────────────────────────────────
    indexers.append(("snapshot", """
        SELECT id, name, description, project_id, project_name,
               tenant_name, domain_name, domain_id, volume_id,
               size_gb, status, created_at, last_seen_at
        FROM snapshots
        WHERE last_seen_at > %s
        ORDER BY last_seen_at
    """, lambda r: {
        "resource_id": r["id"],
        "resource_name": _safe(r.get("name")),
        "tenant_id": r.get("project_id"),
        "tenant_name": _safe(r.get("tenant_name") or r.get("project_name")),
        "domain_id": _safe(r.get("domain_id")),
        "domain_name": _safe(r.get("domain_name")),
        "title": f"Snapshot: {_safe(r.get('name'))} ({_safe(r.get('status'))})",
        "body_text": " | ".join(filter(None, [
            f"Volume snapshot {_safe(r.get('name'))} is {_safe(r.get('status'))}",
            f"Size: {r.get('size_gb', 0)} GB" if r.get("size_gb") else None,
            f"Source volume: {_safe(r.get('volume_id'))}",
            f"Project: {_safe(r.get('project_name') or r.get('tenant_name'))}, Domain: {_safe(r.get('domain_name'))}",
            f"Description: {_safe(r.get('description'))}" if r.get("description") else None,
        ])),
        "ts": r.get("last_seen_at") or r.get("created_at"),
        "metadata": {
            "status": _safe(r.get("status")),
            "size_gb": r.get("size_gb"),
            "project": _safe(r.get("project_name") or r.get("tenant_name")),
            "domain": _safe(r.get("domain_name")),
        },
    }))

    # ── Hypervisors ──────────────────────────────────────────
    indexers.append(("hypervisor", """
        SELECT h.id, h.hostname, h.hypervisor_type, h.vcpus, h.memory_mb,
               h.local_gb, h.state, h.status, h.last_seen_at,
               (SELECT COUNT(*) FROM servers s WHERE s.hypervisor_hostname = h.hostname) AS vm_count
        FROM hypervisors h
        WHERE h.last_seen_at > %s
        ORDER BY h.last_seen_at
    """, lambda r: {
        "resource_id": r["id"],
        "resource_name": r.get("hostname"),
        "tenant_id": None, "tenant_name": "",
        "domain_id": None, "domain_name": "",
        "title": f"Hypervisor: {_safe(r.get('hostname'))} ({_safe(r.get('state'))})",
        "body_text": " | ".join(filter(None, [
            f"Compute host {_safe(r.get('hostname'))} is {_safe(r.get('state'))}/{_safe(r.get('status'))}",
            f"Capacity: {r.get('vcpus', 0)} vCPUs, {r.get('memory_mb', 0)}MB RAM, {r.get('local_gb', 0)}GB local disk",
            f"Type: {_safe(r.get('hypervisor_type'))}",
            f"Hosting {r.get('vm_count', 0)} VMs",
        ])),
        "ts": r.get("last_seen_at"),
        "metadata": {
            "state": _safe(r.get("state")),
            "status": _safe(r.get("status")),
            "hypervisor_type": _safe(r.get("hypervisor_type")),
            "vcpus": r.get("vcpus"),
            "memory_mb": r.get("memory_mb"),
            "local_gb": r.get("local_gb"),
            "vm_count": r.get("vm_count", 0),
        },
    }))

    # ── Networks ─────────────────────────────────────────────
    indexers.append(("network", """
        SELECT n.id, n.name, n.project_id, p.name AS project_name,
               d.name AS domain_name, d.id AS domain_id,
               n.is_shared, n.is_external, n.last_seen_at,
               (SELECT COUNT(*) FROM subnets sub WHERE sub.network_id = n.id) AS subnet_count,
               (SELECT COUNT(*) FROM ports po WHERE po.network_id = n.id) AS port_count
        FROM networks n
        LEFT JOIN projects p ON n.project_id = p.id
        LEFT JOIN domains d ON p.domain_id = d.id
        WHERE n.last_seen_at > %s
        ORDER BY n.last_seen_at
    """, lambda r: {
        "resource_id": r["id"],
        "resource_name": _safe(r.get("name")),
        "tenant_id": r.get("project_id"),
        "tenant_name": _safe(r.get("project_name")),
        "domain_id": _safe(r.get("domain_id")),
        "domain_name": _safe(r.get("domain_name")),
        "title": f"Network: {_safe(r.get('name'))}",
        "body_text": " | ".join(filter(None, [
            f"Network {_safe(r.get('name'))} in project {_safe(r.get('project_name'))}",
            "Shared network" if r.get("is_shared") else "Private network",
            "External (provider) network" if r.get("is_external") else "Internal tenant network",
            f"{r.get('subnet_count', 0)} subnets, {r.get('port_count', 0)} ports",
        ])),
        "ts": r.get("last_seen_at"),
        "metadata": {
            "is_shared": r.get("is_shared"),
            "is_external": r.get("is_external"),
            "subnet_count": r.get("subnet_count", 0),
            "port_count": r.get("port_count", 0),
            "project": _safe(r.get("project_name")),
        },
    }))

    # ── Subnets ──────────────────────────────────────────────
    indexers.append(("subnet", """
        SELECT s.id, s.name, s.network_id, s.cidr, s.gateway_ip,
               s.last_seen_at,
               n.name AS network_name
        FROM subnets s
        LEFT JOIN networks n ON s.network_id = n.id
        WHERE s.last_seen_at > %s
        ORDER BY s.last_seen_at
    """, lambda r: {
        "resource_id": r["id"],
        "resource_name": _safe(r.get("name")),
        "tenant_id": None, "tenant_name": "",
        "domain_id": None, "domain_name": "",
        "title": f"Subnet: {_safe(r.get('name'))} ({_safe(r.get('cidr'))})",
        "body_text": " | ".join(filter(None, [
            f"Subnet {_safe(r.get('name'))} with CIDR {_safe(r.get('cidr'))}",
            f"Gateway: {_safe(r.get('gateway_ip'))}" if r.get("gateway_ip") else "No gateway",
            f"Attached to network: {_safe(r.get('network_name') or r.get('network_id'))}",
        ])),
        "ts": r.get("last_seen_at"),
        "metadata": {
            "cidr": _safe(r.get("cidr")),
            "gateway_ip": _safe(r.get("gateway_ip")),
            "network": _safe(r.get("network_name")),
        },
    }))

    # ── Floating IPs ─────────────────────────────────────────
    indexers.append(("floating_ip", """
        SELECT f.id, f.floating_ip, f.fixed_ip, f.port_id,
               f.project_id, p.name AS project_name,
               d.name AS domain_name, d.id AS domain_id,
               f.status, f.last_seen_at
        FROM floating_ips f
        LEFT JOIN projects p ON f.project_id = p.id
        LEFT JOIN domains d ON p.domain_id = d.id
        WHERE f.last_seen_at > %s
        ORDER BY f.last_seen_at
    """, lambda r: {
        "resource_id": r["id"],
        "resource_name": _safe(r.get("floating_ip")),
        "tenant_id": r.get("project_id"),
        "tenant_name": _safe(r.get("project_name")),
        "domain_id": _safe(r.get("domain_id")),
        "domain_name": _safe(r.get("domain_name")),
        "title": f"Floating IP: {_safe(r.get('floating_ip'))} → {_safe(r.get('fixed_ip'))}",
        "body_text": " | ".join(filter(None, [
            f"Floating IP {_safe(r.get('floating_ip'))} mapped to fixed IP {_safe(r.get('fixed_ip'))}" if r.get("fixed_ip") else f"Floating IP {_safe(r.get('floating_ip'))} (unassigned)",
            f"Status: {_safe(r.get('status'))}",
            f"Project: {_safe(r.get('project_name'))}, Domain: {_safe(r.get('domain_name'))}",
        ])),
        "ts": r.get("last_seen_at"),
        "metadata": {
            "status": _safe(r.get("status")),
            "floating_ip": _safe(r.get("floating_ip")),
            "fixed_ip": _safe(r.get("fixed_ip")),
            "project": _safe(r.get("project_name")),
        },
    }))

    # ── Ports ────────────────────────────────────────────────
    indexers.append(("port", """
        SELECT po.id, po.name, po.network_id, po.project_id,
               po.device_id, po.device_owner, po.mac_address,
               po.ip_addresses, po.last_seen_at,
               p.name AS project_name,
               d.name AS domain_name, d.id AS domain_id,
               n.name AS network_name
        FROM ports po
        LEFT JOIN projects p ON po.project_id = p.id
        LEFT JOIN domains d ON p.domain_id = d.id
        LEFT JOIN networks n ON po.network_id = n.id
        WHERE po.last_seen_at > %s
        ORDER BY po.last_seen_at
    """, lambda r: {
        "resource_id": r["id"],
        "resource_name": _safe(r.get("name")) or _safe(r.get("mac_address")),
        "tenant_id": r.get("project_id"),
        "tenant_name": _safe(r.get("project_name")),
        "domain_id": _safe(r.get("domain_id")),
        "domain_name": _safe(r.get("domain_name")),
        "title": f"Port: {_safe(r.get('name') or r.get('mac_address'))}",
        "body_text": " | ".join(filter(None, [
            f"Port {_safe(r.get('name') or r.get('mac_address'))} on network {_safe(r.get('network_name') or r.get('network_id'))}",
            f"MAC: {_safe(r.get('mac_address'))}",
            f"Device: {_safe(r.get('device_owner'))}" if r.get("device_owner") else "Unattached",
            f"IPs: {json.dumps(r['ip_addresses'])}" if r.get("ip_addresses") else None,
            f"Project: {_safe(r.get('project_name'))}" if r.get("project_name") else None,
        ])),
        "ts": r.get("last_seen_at"),
        "metadata": {
            "mac_address": _safe(r.get("mac_address")),
            "device_owner": _safe(r.get("device_owner")),
            "network": _safe(r.get("network_name")),
            "project": _safe(r.get("project_name")),
        },
    }))

    # ── Security Groups ──────────────────────────────────────
    indexers.append(("security_group", """
        SELECT sg.id, sg.name, sg.description, sg.project_id, sg.project_name,
               sg.tenant_name, sg.domain_id, sg.domain_name,
               sg.created_at, sg.updated_at,
               (SELECT COUNT(*) FROM security_group_rules r WHERE r.security_group_id = sg.id) AS rule_count
        FROM security_groups sg
        WHERE COALESCE(sg.updated_at, sg.created_at) > %s
        ORDER BY COALESCE(sg.updated_at, sg.created_at)
    """, lambda r: {
        "resource_id": r["id"],
        "resource_name": _safe(r.get("name")),
        "tenant_id": r.get("project_id"),
        "tenant_name": _safe(r.get("tenant_name") or r.get("project_name")),
        "domain_id": _safe(r.get("domain_id")),
        "domain_name": _safe(r.get("domain_name")),
        "title": f"Security Group: {_safe(r.get('name'))}",
        "body_text": " | ".join(filter(None, [
            f"Security group {_safe(r.get('name'))} with {r.get('rule_count', 0)} firewall rules",
            f"Description: {_safe(r.get('description'))}" if r.get("description") else None,
            f"Project: {_safe(r.get('project_name') or r.get('tenant_name'))}, Domain: {_safe(r.get('domain_name'))}",
        ])),
        "ts": r.get("updated_at") or r.get("created_at"),
        "metadata": {
            "rule_count": r.get("rule_count", 0),
            "project": _safe(r.get("project_name") or r.get("tenant_name")),
            "domain": _safe(r.get("domain_name")),
        },
    }))

    # ── Activity Log ─────────────────────────────────────────
    indexers.append(("activity", """
        SELECT id, timestamp, actor, action, resource_type,
               resource_id, resource_name, domain_id, domain_name,
               details, ip_address, result, error_message
        FROM activity_log
        WHERE timestamp > %s
        ORDER BY timestamp
    """, lambda r: {
        "resource_id": str(r["id"]),
        "resource_name": _safe(r.get("resource_name")),
        "tenant_id": None,
        "tenant_name": "",
        "domain_id": _safe(r.get("domain_id")),
        "domain_name": _safe(r.get("domain_name")),
        "title": f"Activity: {_safe(r.get('actor'))} {_safe(r.get('action'))} {_safe(r.get('resource_type'))} {_safe(r.get('resource_name'))}",
        "body_text": " | ".join(filter(None, [
            f"{_safe(r.get('actor'))} performed {_safe(r.get('action'))} on {_safe(r.get('resource_type'))} {_safe(r.get('resource_name'))}",
            f"Result: {_safe(r.get('result'))}" if r.get("result") else None,
            f"Error: {_safe(r.get('error_message'))}" if r.get("error_message") else None,
            f"From IP: {_safe(r.get('ip_address'))}" if r.get("ip_address") else None,
            f"Domain: {_safe(r.get('domain_name'))}" if r.get("domain_name") else None,
        ])),
        "ts": r.get("timestamp"),
        "metadata": {
            "actor": _safe(r.get("actor")),
            "action": _safe(r.get("action")),
            "resource_type": _safe(r.get("resource_type")),
            "status": _safe(r.get("result")),
        },
    }))

    # ── Auth Audit Log ───────────────────────────────────────
    indexers.append(("audit", """
        SELECT id, username, action, resource, endpoint,
               ip_address, user_agent, timestamp, success, details
        FROM auth_audit_log
        WHERE timestamp > %s
        ORDER BY timestamp
    """, lambda r: {
        "resource_id": str(r["id"]),
        "resource_name": _safe(r.get("resource")),
        "tenant_id": None, "tenant_name": "",
        "domain_id": None, "domain_name": "",
        "title": f"Auth: {_safe(r.get('username'))} {_safe(r.get('action'))} ({('success' if r.get('success') else 'failed')})",
        "body_text": " | ".join(filter(None, [
            f"User {_safe(r.get('username'))} attempted {_safe(r.get('action'))} — {'succeeded' if r.get('success') else 'FAILED'}",
            f"Endpoint: {_safe(r.get('endpoint'))}" if r.get("endpoint") else None,
            f"Resource: {_safe(r.get('resource'))}" if r.get("resource") else None,
            f"From IP: {_safe(r.get('ip_address'))}" if r.get("ip_address") else None,
            f"Agent: {_safe(r.get('user_agent'))}" if r.get("user_agent") else None,
        ])),
        "ts": r.get("timestamp"),
        "metadata": {
            "action": _safe(r.get("action")),
            "status": "Success" if r.get("success") else "Failed",
            "username": _safe(r.get("username")),
        },
    }))

    # ── Drift Events ─────────────────────────────────────────
    indexers.append(("drift_event", """
        SELECT id, resource_type, resource_id, resource_name,
               project_id, project_name, domain_id, domain_name,
               severity, field_changed, old_value, new_value,
               description, detected_at, acknowledged
        FROM drift_events
        WHERE detected_at > %s
        ORDER BY detected_at
    """, lambda r: {
        "resource_id": str(r["id"]),
        "resource_name": _safe(r.get("resource_name")),
        "tenant_id": r.get("project_id"),
        "tenant_name": _safe(r.get("project_name")),
        "domain_id": _safe(r.get("domain_id")),
        "domain_name": _safe(r.get("domain_name")),
        "title": f"Drift: {_safe(r.get('resource_name'))} {_safe(r.get('field_changed'))} changed ({_safe(r.get('severity'))})",
        "body_text": " | ".join(filter(None, [
            f"Configuration drift detected on {_safe(r.get('resource_type'))} {_safe(r.get('resource_name'))}",
            f"Field '{_safe(r.get('field_changed'))}' changed from '{_safe(r.get('old_value'))}' to '{_safe(r.get('new_value'))}'",
            f"Severity: {_safe(r.get('severity'))}",
            f"Description: {_safe(r.get('description'))}" if r.get("description") else None,
            f"Project: {_safe(r.get('project_name'))}, Domain: {_safe(r.get('domain_name'))}",
            "Acknowledged" if r.get("acknowledged") else "Not yet acknowledged",
        ])),
        "ts": r.get("detected_at"),
        "metadata": {
            "severity": _safe(r.get("severity")),
            "field_changed": _safe(r.get("field_changed")),
            "old_value": _safe(r.get("old_value")),
            "new_value": _safe(r.get("new_value")),
            "acknowledged": r.get("acknowledged"),
            "project": _safe(r.get("project_name")),
        },
    }))

    # ── Snapshot Runs ────────────────────────────────────────
    indexers.append(("snapshot_run", """
        SELECT id, run_type, started_at, finished_at, status,
               total_volumes, snapshots_created, snapshots_deleted,
               snapshots_failed, triggered_by, trigger_source,
               error_summary
        FROM snapshot_runs
        WHERE started_at > %s
        ORDER BY started_at
    """, lambda r: {
        "resource_id": str(r["id"]),
        "resource_name": f"Run #{r['id']}",
        "tenant_id": None, "tenant_name": "",
        "domain_id": None, "domain_name": "",
        "title": f"Snapshot Run: {_safe(r.get('run_type'))} ({_safe(r.get('status'))}) — {r.get('snapshots_created', 0)} created, {r.get('snapshots_failed', 0)} failed",
        "body_text": " | ".join(filter(None, [
            f"Snapshot {_safe(r.get('run_type'))} run finished with status {_safe(r.get('status'))}",
            f"Processed {r.get('total_volumes', 0)} volumes: {r.get('snapshots_created', 0)} created, {r.get('snapshots_deleted', 0)} deleted, {r.get('snapshots_failed', 0)} failed",
            f"Triggered by: {_safe(r.get('triggered_by'))} via {_safe(r.get('trigger_source'))}",
            f"Error: {_safe(r.get('error_summary'))}" if r.get("error_summary") else None,
        ])),
        "ts": r.get("started_at"),
        "metadata": {
            "status": _safe(r.get("status")),
            "run_type": _safe(r.get("run_type")),
            "snapshots_created": r.get("snapshots_created", 0),
            "snapshots_failed": r.get("snapshots_failed", 0),
            "total_volumes": r.get("total_volumes", 0),
        },
    }))

    # ── Snapshot Records ─────────────────────────────────────
    indexers.append(("snapshot_record", """
        SELECT id, snapshot_run_id, action, snapshot_id,
               snapshot_name, volume_id, volume_name,
               tenant_id, tenant_name, project_id, project_name,
               vm_id, vm_name, policy_name, size_gb,
               status, error_message
        FROM snapshot_records
        WHERE id > COALESCE((
            SELECT CAST(docs_count AS INTEGER)
            FROM search_indexer_state WHERE doc_type = 'snapshot_record'
        ), 0)
        ORDER BY id
    """, lambda r: {
        "resource_id": str(r["id"]),
        "resource_name": _safe(r.get("snapshot_name")),
        "tenant_id": r.get("tenant_id") or r.get("project_id"),
        "tenant_name": _safe(r.get("tenant_name") or r.get("project_name")),
        "domain_id": None, "domain_name": "",
        "title": f"Snapshot {_safe(r.get('action'))}: {_safe(r.get('snapshot_name'))} on {_safe(r.get('vm_name'))} ({_safe(r.get('status'))})",
        "body_text": " | ".join(filter(None, [
            f"Snapshot {_safe(r.get('action'))} of {_safe(r.get('snapshot_name'))} — status: {_safe(r.get('status'))}",
            f"VM: {_safe(r.get('vm_name'))}, Volume: {_safe(r.get('volume_name'))}",
            f"Policy: {_safe(r.get('policy_name'))}" if r.get("policy_name") else "Manual snapshot",
            f"Size: {r.get('size_gb', 0)} GB" if r.get("size_gb") else None,
            f"Project: {_safe(r.get('project_name') or r.get('tenant_name'))}",
            f"Error: {_safe(r.get('error_message'))}" if r.get("error_message") else None,
        ])),
        "ts": datetime.now(timezone.utc),  # no timestamp column
        "metadata": {
            "status": _safe(r.get("status")),
            "action": _safe(r.get("action")),
            "policy_name": _safe(r.get("policy_name")),
            "vm_name": _safe(r.get("vm_name")),
            "size_gb": r.get("size_gb"),
        },
    }))

    # ── Restore Jobs ─────────────────────────────────────────
    indexers.append(("restore_job", """
        SELECT id, created_by, project_id, project_name,
               vm_id, vm_name, restore_point_id, restore_point_name,
               mode, status, requested_name, failure_reason,
               created_at
        FROM restore_jobs
        WHERE created_at > %s
        ORDER BY created_at
    """, lambda r: {
        "resource_id": str(r["id"]),
        "resource_name": _safe(r.get("requested_name") or r.get("vm_name")),
        "tenant_id": r.get("project_id"),
        "tenant_name": _safe(r.get("project_name")),
        "domain_id": None, "domain_name": "",
        "title": f"Restore: {_safe(r.get('vm_name'))} → {_safe(r.get('requested_name'))} ({_safe(r.get('status'))})",
        "body_text": " | ".join(filter(None, [
            f"Restore job for VM {_safe(r.get('vm_name'))} to {_safe(r.get('requested_name'))} ({_safe(r.get('mode'))} mode)",
            f"Status: {_safe(r.get('status'))}",
            f"Restore point: {_safe(r.get('restore_point_name'))}",
            f"Created by: {_safe(r.get('created_by'))}",
            f"Project: {_safe(r.get('project_name'))}",
            f"Failure reason: {_safe(r.get('failure_reason'))}" if r.get("failure_reason") else None,
        ])),
        "ts": r.get("created_at"),
        "metadata": {
            "status": _safe(r.get("status")),
            "mode": _safe(r.get("mode")),
            "vm_name": _safe(r.get("vm_name")),
            "created_by": _safe(r.get("created_by")),
        },
    }))

    # ── Backup History ───────────────────────────────────────
    indexers.append(("backup", """
        SELECT id, status, backup_type, backup_target, file_name,
               file_path, file_size_bytes, duration_seconds,
               initiated_by, error_message, started_at, completed_at
        FROM backup_history
        WHERE started_at > %s
        ORDER BY started_at
    """, lambda r: {
        "resource_id": str(r["id"]),
        "resource_name": _safe(r.get("file_name")),
        "tenant_id": None, "tenant_name": "",
        "domain_id": None, "domain_name": "",
        "title": f"Backup: {_safe(r.get('backup_type'))} {_safe(r.get('backup_target'))} ({_safe(r.get('status'))})",
        "body_text": " | ".join(filter(None, [
            f"{_safe(r.get('backup_type'))} backup of {_safe(r.get('backup_target'))} completed with status {_safe(r.get('status'))}",
            f"File: {_safe(r.get('file_name'))}",
            f"Size: {round(r.get('file_size_bytes', 0) / 1048576)} MB" if r.get("file_size_bytes") else None,
            f"Duration: {r.get('duration_seconds', 0)} seconds" if r.get("duration_seconds") else None,
            f"Initiated by: {_safe(r.get('initiated_by'))}",
            f"Error: {_safe(r.get('error_message'))}" if r.get("error_message") else None,
        ])),
        "ts": r.get("started_at"),
        "metadata": {
            "status": _safe(r.get("status")),
            "backup_type": _safe(r.get("backup_type")),
            "size_mb": round(r.get("file_size_bytes", 0) / 1048576) if r.get("file_size_bytes") else None,
            "duration_seconds": r.get("duration_seconds"),
        },
    }))

    # ── Notification Log ─────────────────────────────────────
    indexers.append(("notification", """
        SELECT id, username, email, event_type, subject,
               body_preview, delivery_status, error_message,
               sent_at, created_at
        FROM notification_log
        WHERE created_at > %s
        ORDER BY created_at
    """, lambda r: {
        "resource_id": str(r["id"]),
        "resource_name": _safe(r.get("subject")),
        "tenant_id": None, "tenant_name": "",
        "domain_id": None, "domain_name": "",
        "title": f"Notification: {_safe(r.get('subject'))} ({_safe(r.get('delivery_status'))})",
        "body_text": " | ".join(filter(None, [
            f"Notification to {_safe(r.get('username'))} ({_safe(r.get('email'))}) — {_safe(r.get('delivery_status'))}",
            f"Event: {_safe(r.get('event_type'))}",
            f"Subject: {_safe(r.get('subject'))}",
            f"Preview: {_safe(r.get('body_preview'))}" if r.get("body_preview") else None,
            f"Error: {_safe(r.get('error_message'))}" if r.get("error_message") else None,
        ])),
        "ts": r.get("sent_at") or r.get("created_at"),
        "metadata": {
            "event_type": _safe(r.get("event_type")),
            "status": _safe(r.get("delivery_status")),
            "email": _safe(r.get("email")),
        },
    }))

    # ── Provisioning Jobs ────────────────────────────────────
    indexers.append(("provisioning", """
        SELECT id, job_id, domain_name, project_name, username,
               user_email, status, created_by, error_message,
               network_name, network_type, subnet_cidr,
               created_at
        FROM provisioning_jobs
        WHERE created_at > %s
        ORDER BY created_at
    """, lambda r: {
        "resource_id": _safe(r.get("job_id") or r.get("id")),
        "resource_name": _safe(r.get("project_name")),
        "tenant_id": None,
        "tenant_name": _safe(r.get("project_name")),
        "domain_id": None,
        "domain_name": _safe(r.get("domain_name")),
        "title": f"Provisioning: {_safe(r.get('domain_name'))}/{_safe(r.get('project_name'))} ({_safe(r.get('status'))})",
        "body_text": " | ".join(filter(None, [
            f"Provisioning job for domain {_safe(r.get('domain_name'))}, project {_safe(r.get('project_name'))} — status: {_safe(r.get('status'))}",
            f"User: {_safe(r.get('username'))} ({_safe(r.get('user_email'))})",
            f"Network: {_safe(r.get('network_name'))} ({_safe(r.get('network_type'))}), Subnet: {_safe(r.get('subnet_cidr'))}" if r.get("network_name") else None,
            f"Created by: {_safe(r.get('created_by'))}",
            f"Error: {_safe(r.get('error_message'))}" if r.get("error_message") else None,
        ])),
        "ts": r.get("created_at"),
        "metadata": {
            "status": _safe(r.get("status")),
            "domain": _safe(r.get("domain_name")),
            "network_type": _safe(r.get("network_type")),
        },
    }))

    # ── Deletions History ────────────────────────────────────
    indexers.append(("deletion", """
        SELECT id, resource_type, resource_id, resource_name,
               deleted_at, project_name, domain_name, reason
        FROM deletions_history
        WHERE deleted_at > %s
        ORDER BY deleted_at
    """, lambda r: {
        "resource_id": _safe(r.get("resource_id")),
        "resource_name": _safe(r.get("resource_name")),
        "tenant_id": None,
        "tenant_name": _safe(r.get("project_name")),
        "domain_id": None,
        "domain_name": _safe(r.get("domain_name")),
        "title": f"Deleted {_safe(r.get('resource_type'))}: {_safe(r.get('resource_name'))}",
        "body_text": " | ".join(filter(None, [
            f"{_safe(r.get('resource_type'))} {_safe(r.get('resource_name'))} was deleted",
            f"Reason: {_safe(r.get('reason'))}" if r.get("reason") else None,
            f"Project: {_safe(r.get('project_name'))}, Domain: {_safe(r.get('domain_name'))}",
            f"Original ID: {_safe(r.get('resource_id'))}",
        ])),
        "ts": r.get("deleted_at"),
        "metadata": {
            "resource_type": _safe(r.get("resource_type")),
            "reason": _safe(r.get("reason")),
            "project": _safe(r.get("project_name")),
        },
    }))

    # ── Domains ──────────────────────────────────────────────
    indexers.append(("domain", """
        SELECT d.id, d.name, d.last_seen_at,
               (SELECT COUNT(*) FROM projects p WHERE p.domain_id = d.id) AS project_count,
               (SELECT COUNT(*) FROM users u WHERE u.domain_id = d.id) AS user_count,
               (SELECT COUNT(*) FROM servers s
                JOIN projects p ON s.project_id = p.id
                WHERE p.domain_id = d.id) AS vm_count,
               (SELECT COUNT(*) FROM role_assignments ra WHERE ra.domain_id = d.id) AS role_count,
               (SELECT string_agg(DISTINCT p2.name, ', ' ORDER BY p2.name)
                FROM projects p2 WHERE p2.domain_id = d.id) AS project_names,
               d.raw_json
        FROM domains d
        WHERE d.last_seen_at > %s
        ORDER BY d.last_seen_at
    """, lambda r: {
        "resource_id": _safe(r.get("id")),
        "resource_name": _safe(r.get("name")),
        "tenant_id": None,
        "tenant_name": None,
        "domain_id": _safe(r.get("id")),
        "domain_name": _safe(r.get("name")),
        "title": f"Domain: {_safe(r.get('name'))}",
        "body_text": " | ".join(filter(None, [
            f"Domain {_safe(r.get('name'))} is an organizational unit",
            f"containing {r.get('project_count', 0)} projects, {r.get('user_count', 0)} users, and {r.get('vm_count', 0)} VMs",
            f"with {r.get('role_count', 0)} role assignments",
            f"Projects: {_safe(r.get('project_names'))}" if r.get("project_names") else None,
            f"Enabled: {_json_extract(r.get('raw_json'), 'enabled')}" if r.get("raw_json") else "Enabled: true",
            _safe(r.get("id")),
        ])),
        "ts": r.get("last_seen_at"),
        "metadata": {
            "project_count": r.get("project_count", 0),
            "user_count": r.get("user_count", 0),
            "vm_count": r.get("vm_count", 0),
            "role_count": r.get("role_count", 0),
            "enabled": _json_extract(r.get("raw_json"), "enabled") or "true",
            "projects": _safe(r.get("project_names")),
        },
    }))

    # ── Projects ─────────────────────────────────────────────
    indexers.append(("project", """
        SELECT p.id, p.name, p.domain_id,
               d.name AS domain_name,
               p.last_seen_at,
               (SELECT COUNT(*) FROM servers s WHERE s.project_id = p.id) AS vm_count,
               (SELECT COUNT(*) FROM volumes v WHERE v.project_id = p.id) AS volume_count,
               (SELECT COUNT(*) FROM networks n WHERE n.project_id = p.id) AS network_count,
               (SELECT COUNT(*) FROM floating_ips f WHERE f.project_id = p.id) AS fip_count,
               (SELECT COUNT(*) FROM role_assignments ra WHERE ra.project_id = p.id) AS member_count,
               (SELECT string_agg(DISTINCT ra2.user_name, ', ' ORDER BY ra2.user_name)
                FROM role_assignments ra2 WHERE ra2.project_id = p.id
                AND ra2.user_name IS NOT NULL) AS members,
               p.raw_json
        FROM projects p
        LEFT JOIN domains d ON p.domain_id = d.id
        WHERE p.last_seen_at > %s
        ORDER BY p.last_seen_at
    """, lambda r: {
        "resource_id": _safe(r.get("id")),
        "resource_name": _safe(r.get("name")),
        "tenant_id": _safe(r.get("id")),
        "tenant_name": _safe(r.get("name")),
        "domain_id": _safe(r.get("domain_id")),
        "domain_name": _safe(r.get("domain_name")),
        "title": f"Project: {_safe(r.get('name'))} ({_safe(r.get('domain_name'))})",
        "body_text": " | ".join(filter(None, [
            f"Project {_safe(r.get('name'))} belongs to domain {_safe(r.get('domain_name'))}",
            f"Resources: {r.get('vm_count', 0)} VMs, {r.get('volume_count', 0)} volumes, {r.get('network_count', 0)} networks, {r.get('fip_count', 0)} floating IPs",
            f"{r.get('member_count', 0)} members with role assignments",
            f"Members: {_safe(r.get('members'))}" if r.get("members") else None,
            f"Enabled: {_json_extract(r.get('raw_json'), 'enabled')}" if r.get("raw_json") else "Enabled: true",
            _safe(r.get("id")),
        ])),
        "ts": r.get("last_seen_at"),
        "metadata": {
            "domain": _safe(r.get("domain_name")),
            "vm_count": r.get("vm_count", 0),
            "volume_count": r.get("volume_count", 0),
            "network_count": r.get("network_count", 0),
            "fip_count": r.get("fip_count", 0),
            "member_count": r.get("member_count", 0),
            "enabled": _json_extract(r.get("raw_json"), "enabled") or "true",
        },
    }))

    # ── Users (Platform9/Keystone users) ─────────────────────
    indexers.append(("user", """
        SELECT u.id, u.name, u.email, u.enabled, u.description,
               u.domain_id, d.name AS domain_name,
               u.default_project_id, u.password_expires_at,
               u.created_at, u.last_login, u.last_seen_at,
               (SELECT COUNT(*) FROM role_assignments ra WHERE ra.user_id = u.id) AS role_count,
               (SELECT string_agg(DISTINCT ra2.role_name, ', ' ORDER BY ra2.role_name)
                FROM role_assignments ra2 WHERE ra2.user_id = u.id) AS roles,
               (SELECT string_agg(DISTINCT COALESCE(ra3.project_name, ra3.domain_name), ', ')
                FROM role_assignments ra3 WHERE ra3.user_id = u.id
                AND (ra3.project_name IS NOT NULL OR ra3.domain_name IS NOT NULL)) AS scopes,
               dp.name AS default_project_name
        FROM users u
        LEFT JOIN domains d ON u.domain_id = d.id
        LEFT JOIN projects dp ON u.default_project_id = dp.id
        WHERE u.last_seen_at > %s
        ORDER BY u.last_seen_at
    """, lambda r: {
        "resource_id": _safe(r.get("id")),
        "resource_name": _safe(r.get("name")),
        "tenant_id": _safe(r.get("default_project_id")),
        "tenant_name": _safe(r.get("default_project_name")),
        "domain_id": _safe(r.get("domain_id")),
        "domain_name": _safe(r.get("domain_name")),
        "title": f"User: {_safe(r.get('name'))} ({_safe(r.get('domain_name'))})",
        "body_text": " | ".join(filter(None, [
            f"User {_safe(r.get('name'))} in domain {_safe(r.get('domain_name'))}",
            f"Email: {_safe(r.get('email'))}" if r.get("email") else None,
            f"Status: {'enabled' if r.get('enabled') else 'disabled'}",
            f"Roles: {_safe(r.get('roles'))}" if r.get("roles") else "No role assignments",
            f"{r.get('role_count', 0)} role assignments across: {_safe(r.get('scopes'))}" if r.get("scopes") else None,
            f"Default project: {_safe(r.get('default_project_name'))}" if r.get("default_project_name") else None,
            f"Last login: {r.get('last_login')}" if r.get("last_login") else "Never logged in",
            f"Description: {_safe(r.get('description'))}" if r.get("description") else None,
        ])),
        "ts": r.get("last_seen_at"),
        "metadata": {
            "email": _safe(r.get("email")),
            "enabled": r.get("enabled"),
            "domain": _safe(r.get("domain_name")),
            "roles": _safe(r.get("roles")),
            "role_count": r.get("role_count", 0),
            "default_project": _safe(r.get("default_project_name")),
            "last_login": str(r.get("last_login")) if r.get("last_login") else None,
        },
    }))

    # ── Flavors ──────────────────────────────────────────────
    indexers.append(("flavor", """
        SELECT f.id, f.name, f.vcpus, f.ram_mb, f.disk_gb,
               f.ephemeral_gb, f.swap_mb, f.is_public, f.last_seen_at,
               (SELECT COUNT(*) FROM servers s WHERE s.flavor_id = f.id) AS vm_count
        FROM flavors f
        WHERE f.last_seen_at > %s
        ORDER BY f.last_seen_at
    """, lambda r: {
        "resource_id": _safe(r.get("id")),
        "resource_name": _safe(r.get("name")),
        "tenant_id": None,
        "tenant_name": None,
        "domain_id": None,
        "domain_name": None,
        "title": f"Flavor: {_safe(r.get('name'))} ({r.get('vcpus',0)} vCPU, {r.get('ram_mb',0)}MB, {r.get('disk_gb',0)}GB)",
        "body_text": " | ".join(filter(None, [
            f"Flavor {_safe(r.get('name'))} defines a VM size template",
            f"Specs: {r.get('vcpus', 0)} vCPUs, {r.get('ram_mb', 0)}MB RAM, {r.get('disk_gb', 0)}GB root disk",
            f"Ephemeral: {r.get('ephemeral_gb', 0)}GB, Swap: {r.get('swap_mb', 0)}MB" if r.get("ephemeral_gb") or r.get("swap_mb") else None,
            "Public flavor (available to all projects)" if r.get("is_public") else "Private flavor (restricted)",
            f"Currently used by {r.get('vm_count', 0)} VMs",
        ])),
        "ts": r.get("last_seen_at"),
        "metadata": {
            "vcpus": r.get("vcpus"),
            "ram_mb": r.get("ram_mb"),
            "disk_gb": r.get("disk_gb"),
            "is_public": r.get("is_public"),
            "vm_count": r.get("vm_count", 0),
        },
    }))

    # ── Images ───────────────────────────────────────────────
    indexers.append(("image", """
        SELECT id, name, status, visibility, protected,
               size_bytes, disk_format, container_format,
               checksum, created_at, updated_at, last_seen_at
        FROM images
        WHERE last_seen_at > %s
        ORDER BY last_seen_at
    """, lambda r: {
        "resource_id": _safe(r.get("id")),
        "resource_name": _safe(r.get("name")),
        "tenant_id": None,
        "tenant_name": None,
        "domain_id": None,
        "domain_name": None,
        "title": f"Image: {_safe(r.get('name'))} ({_safe(r.get('disk_format'))})",
        "body_text": " | ".join(filter(None, [
            f"Glance image {_safe(r.get('name'))} ({_safe(r.get('status'))})",
            f"Format: {_safe(r.get('disk_format'))}/{_safe(r.get('container_format'))}",
            f"Size: {round(r.get('size_bytes', 0) / 1048576)}MB" if r.get("size_bytes") else "Size: unknown",
            f"Visibility: {_safe(r.get('visibility'))}",
            "Protected image" if r.get("protected") else None,
        ])),
        "ts": r.get("last_seen_at"),
        "metadata": {
            "status": _safe(r.get("status")),
            "visibility": _safe(r.get("visibility")),
            "disk_format": _safe(r.get("disk_format")),
            "size_mb": round(r.get("size_bytes", 0) / 1048576) if r.get("size_bytes") else None,
            "protected": r.get("protected"),
        },
    }))

    # ── Routers ──────────────────────────────────────────────
    indexers.append(("router", """
        SELECT r.id, r.name, r.project_id, r.external_net_id,
               p.name AS project_name, d.name AS domain_name, d.id AS domain_id,
               r.last_seen_at
        FROM routers r
        LEFT JOIN projects p ON r.project_id = p.id
        LEFT JOIN domains d ON p.domain_id = d.id
        WHERE r.last_seen_at > %s
        ORDER BY r.last_seen_at
    """, lambda r: {
        "resource_id": _safe(r.get("id")),
        "resource_name": _safe(r.get("name")),
        "tenant_id": _safe(r.get("project_id")),
        "tenant_name": _safe(r.get("project_name")),
        "domain_id": _safe(r.get("domain_id")),
        "domain_name": _safe(r.get("domain_name")),
        "title": f"Router: {_safe(r.get('name'))}",
        "body_text": " | ".join(filter(None, [
            f"Router {_safe(r.get('name'))} in project {_safe(r.get('project_name'))}",
            f"External network: {_safe(r.get('external_net_id'))}" if r.get("external_net_id") else "No external gateway",
            f"Domain: {_safe(r.get('domain_name'))}",
        ])),
        "ts": r.get("last_seen_at"),
        "metadata": {
            "project": _safe(r.get("project_name")),
            "domain": _safe(r.get("domain_name")),
            "is_external": bool(r.get("external_net_id")),
        },
    }))

    # ── Roles (OpenStack/Keystone) ───────────────────────────
    indexers.append(("role", """
        SELECT r.id, r.name, r.description, r.domain_id,
               d.name AS domain_name, r.last_seen_at
        FROM roles r
        LEFT JOIN domains d ON r.domain_id = d.id
        WHERE r.last_seen_at > %s
        ORDER BY r.last_seen_at
    """, lambda r: {
        "resource_id": _safe(r.get("id")),
        "resource_name": _safe(r.get("name")),
        "tenant_id": None,
        "tenant_name": None,
        "domain_id": _safe(r.get("domain_id")),
        "domain_name": _safe(r.get("domain_name")),
        "title": f"Role: {_safe(r.get('name'))}",
        "body_text": " | ".join(filter(None, [
            f"Keystone role {_safe(r.get('name'))}",
            f"Description: {_safe(r.get('description'))}" if r.get("description") else None,
            f"Domain-scoped: {_safe(r.get('domain_name'))}" if r.get("domain_name") else "Global role",
        ])),
        "ts": r.get("last_seen_at"),
        "metadata": {
            "domain": _safe(r.get("domain_name")),
            "is_global": not bool(r.get("domain_id")),
        },
    }))

    # ── Role Assignments ────────────────────────────────────
    indexers.append(("role_assignment", """
        SELECT ra.id, ra.role_id, ra.user_id, ra.role_name,
               ra.user_name, ra.project_id, ra.project_name,
               ra.domain_id, ra.domain_name, ra.inherited,
               ra.last_seen_at
        FROM role_assignments ra
        WHERE ra.last_seen_at > %s
        ORDER BY ra.last_seen_at
    """, lambda r: {
        "resource_id": str(r.get("id", "")),
        "resource_name": _safe(r.get("user_name")),
        "tenant_id": _safe(r.get("project_id")),
        "tenant_name": _safe(r.get("project_name")),
        "domain_id": _safe(r.get("domain_id")),
        "domain_name": _safe(r.get("domain_name")),
        "title": f"Role Assignment: {_safe(r.get('user_name'))} → {_safe(r.get('role_name'))} on {_safe(r.get('project_name') or r.get('domain_name'))}",
        "body_text": " | ".join(filter(None, [
            f"User {_safe(r.get('user_name'))} assigned role {_safe(r.get('role_name'))}",
            f"Scope: project {_safe(r.get('project_name'))}" if r.get("project_name") else f"Scope: domain {_safe(r.get('domain_name'))}" if r.get("domain_name") else None,
            "Inherited from parent" if r.get("inherited") else "Direct assignment",
        ])),
        "ts": r.get("last_seen_at"),
        "metadata": {
            "role_name": _safe(r.get("role_name")),
            "project": _safe(r.get("project_name")),
            "domain": _safe(r.get("domain_name")),
            "inherited": r.get("inherited"),
        },
    }))

    # ── Groups (Keystone) ───────────────────────────────────
    indexers.append(("group", """
        SELECT g.id, g.name, g.description, g.domain_id,
               d.name AS domain_name, g.last_seen_at
        FROM groups g
        LEFT JOIN domains d ON g.domain_id = d.id
        WHERE g.last_seen_at > %s
        ORDER BY g.last_seen_at
    """, lambda r: {
        "resource_id": _safe(r.get("id")),
        "resource_name": _safe(r.get("name")),
        "tenant_id": None,
        "tenant_name": None,
        "domain_id": _safe(r.get("domain_id")),
        "domain_name": _safe(r.get("domain_name")),
        "title": f"Group: {_safe(r.get('name'))}",
        "body_text": " | ".join(filter(None, [
            f"Keystone group {_safe(r.get('name'))}",
            f"Description: {_safe(r.get('description'))}" if r.get("description") else None,
            f"Domain: {_safe(r.get('domain_name'))}" if r.get("domain_name") else "Global group",
        ])),
        "ts": r.get("last_seen_at"),
        "metadata": {
            "domain": _safe(r.get("domain_name")),
        },
    }))

    # ── Snapshot Policy Sets ────────────────────────────────
    indexers.append(("snapshot_policy", """
        SELECT id, name, description, is_global, tenant_id, tenant_name,
               priority, is_active, created_at, created_by, updated_at, updated_by
        FROM snapshot_policy_sets
        WHERE updated_at > %s
        ORDER BY updated_at
    """, lambda r: {
        "resource_id": str(r.get("id", "")),
        "resource_name": _safe(r.get("name")),
        "tenant_id": _safe(r.get("tenant_id")),
        "tenant_name": _safe(r.get("tenant_name")),
        "domain_id": None,
        "domain_name": None,
        "title": f"Snapshot Policy: {_safe(r.get('name'))} ({'global' if r.get('is_global') else _safe(r.get('tenant_name'))})",
        "body_text": " | ".join(filter(None, [
            f"Snapshot policy {_safe(r.get('name'))} — {'active' if r.get('is_active') else 'inactive'}",
            f"Description: {_safe(r.get('description'))}" if r.get("description") else None,
            "Global policy (applies to all tenants)" if r.get("is_global") else f"Tenant-specific: {_safe(r.get('tenant_name'))}",
            f"Priority: {r.get('priority', 0)}" if r.get("priority") else None,
            f"Created by: {_safe(r.get('created_by'))}",
        ])),
        "ts": r.get("updated_at"),
        "metadata": {
            "is_global": r.get("is_global"),
            "is_active": r.get("is_active"),
            "priority": r.get("priority"),
        },
    }))

    return indexers


# ── Main indexing logic ──────────────────────────────────────

# snapshot_record uses id-based watermark, not timestamp
ID_BASED_TYPES = {"snapshot_record"}

# ── Stale document cleanup ───────────────────────────────────
# Resource doc types whose source rows can be deleted (infrastructure).
# Event/log doc types (activity, audit, snapshot_run, etc.) are excluded
# because those source rows are never deleted — they are permanent records.

RESOURCE_DOC_TYPE_TABLE = {
    "vm":              ("servers",             "id"),
    "volume":          ("volumes",             "id"),
    "snapshot":        ("snapshots",           "id"),
    "hypervisor":      ("hypervisors",         "id"),
    "network":         ("networks",            "id"),
    "subnet":          ("subnets",             "id"),
    "floating_ip":     ("floating_ips",        "id"),
    "port":            ("ports",               "id"),
    "security_group":  ("security_groups",     "id"),
    "domain":          ("domains",             "id"),
    "project":         ("projects",            "id"),
    "user":            ("users",               "id"),
    "flavor":          ("flavors",             "id"),
    "image":           ("images",              "id"),
    "router":          ("routers",             "id"),
    "role":            ("roles",               "id"),
    "role_assignment": ("role_assignments",    "id"),
    "group":           ("groups",              "id"),
    "snapshot_policy": ("snapshot_policy_sets", "id"),
}


def cleanup_stale_documents(conn) -> int:
    """Remove search documents whose source row no longer exists."""
    total_removed = 0
    with conn.cursor() as cur:
        for doc_type, (table, pk) in RESOURCE_DOC_TYPE_TABLE.items():
            try:
                cur.execute(f"""
                    DELETE FROM search_documents sd
                    WHERE sd.doc_type = %s
                      AND NOT EXISTS (
                          SELECT 1 FROM {table} src
                          WHERE src.{pk}::text = sd.resource_id
                      )
                """, (doc_type,))
                removed = cur.rowcount
                if removed > 0:
                    log.info("  %s: removed %d stale documents", doc_type, removed)
                    total_removed += removed
            except Exception as e:
                log.warning("  %s: stale cleanup failed: %s", doc_type, e)
                conn.rollback()
    conn.commit()
    return total_removed

UPSERT_SQL = """
    INSERT INTO search_documents
        (doc_type, tenant_id, tenant_name, domain_id, domain_name,
         resource_id, resource_name, title, body_text, ts, metadata)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (doc_type, resource_id, ts)
    DO UPDATE SET
        tenant_name  = EXCLUDED.tenant_name,
        domain_name  = EXCLUDED.domain_name,
        resource_name = EXCLUDED.resource_name,
        title        = EXCLUDED.title,
        body_text    = EXCLUDED.body_text,
        metadata     = EXCLUDED.metadata
"""


def index_doc_type(conn, doc_type: str, query: str, row_to_doc, batch_size: int = 500):
    """Index one doc_type incrementally."""
    start_time = time.time()

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Get watermark
        cur.execute(
            "SELECT last_indexed_at, docs_count FROM search_indexer_state WHERE doc_type = %s",
            (doc_type,)
        )
        state = cur.fetchone()
        if not state:
            last_indexed = datetime(1970, 1, 1, tzinfo=timezone.utc)
        else:
            last_indexed = state["last_indexed_at"]

        # snapshot_record uses id-based watermark (handled in its query)
        if doc_type in ID_BASED_TYPES:
            cur.execute(query)
        else:
            cur.execute(query, (last_indexed,))

        rows = cur.fetchall()
        if not rows:
            return 0

        # Process in batches
        indexed = 0
        latest_ts = last_indexed

        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            values = []
            for row in batch:
                try:
                    doc = row_to_doc(row)
                    doc_ts = doc.get("ts") or datetime.now(timezone.utc)
                    values.append((
                        doc_type,
                        doc.get("tenant_id"),
                        doc.get("tenant_name", ""),
                        doc.get("domain_id"),
                        doc.get("domain_name", ""),
                        doc["resource_id"],
                        doc.get("resource_name", ""),
                        doc["title"],
                        doc.get("body_text", ""),
                        doc_ts,
                        json.dumps(doc.get("metadata", {})),
                    ))
                    if isinstance(doc_ts, datetime) and doc_ts > latest_ts:
                        latest_ts = doc_ts
                except Exception as e:
                    log.warning("Skipping row in %s: %s", doc_type, e)
                    continue

            if values:
                psycopg2.extras.execute_batch(cur, UPSERT_SQL, values, page_size=100)
                indexed += len(values)

        # Update watermark
        duration_ms = int((time.time() - start_time) * 1000)

        if doc_type in ID_BASED_TYPES:
            # For id-based types, store the max id processed as docs_count
            cur.execute("""
                UPDATE search_indexer_state
                SET docs_count = (SELECT COALESCE(MAX(id), 0) FROM snapshot_records),
                    last_run_at = NOW(),
                    last_run_duration_ms = %s
                WHERE doc_type = %s
            """, (duration_ms, doc_type))
        else:
            cur.execute("""
                UPDATE search_indexer_state
                SET last_indexed_at = %s,
                    docs_count = docs_count + %s,
                    last_run_at = NOW(),
                    last_run_duration_ms = %s
                WHERE doc_type = %s
            """, (latest_ts, indexed, duration_ms, doc_type))

        conn.commit()
        return indexed


def run_indexing_cycle():
    """Run one full indexing cycle across all doc types."""
    log.info("Starting indexing cycle")
    total_start = time.time()
    total_indexed = 0

    try:
        conn = get_conn()
        indexers = _build_indexers()

        for doc_type, query, row_to_doc in indexers:
            try:
                count = index_doc_type(conn, doc_type, query, row_to_doc)
                if count > 0:
                    log.info("  %s: indexed %d documents", doc_type, count)
                total_indexed += count
            except Exception as e:
                log.error("  %s: indexing failed: %s", doc_type, e)
                conn.rollback()

        # Remove search docs for resources that no longer exist
        stale_removed = cleanup_stale_documents(conn)

        conn.close()
    except Exception as e:
        log.error("Indexing cycle failed: %s", e)
        stale_removed = 0

    duration = time.time() - total_start
    log.info("Indexing cycle complete: %d indexed, %d stale removed in %.1fs",
             total_indexed, stale_removed, duration)
    return total_indexed


# ── Main loop ────────────────────────────────────────────────

def main():
    log.info("Search indexer starting (interval=%ds)", INDEX_INTERVAL)

    # Wait for DB to be ready
    for attempt in range(30):
        try:
            conn = get_conn()
            conn.close()
            log.info("Database connection established")
            break
        except Exception:
            log.info("Waiting for database... (%d/30)", attempt + 1)
            time.sleep(5)
    else:
        log.error("Could not connect to database after 30 attempts")
        return

    # Initial full index
    run_indexing_cycle()

    # Periodic incremental indexing
    last_run = time.time()
    while not _shutdown:
        now = time.time()
        if now - last_run >= INDEX_INTERVAL:
            run_indexing_cycle()
            last_run = time.time()
        time.sleep(min(30, INDEX_INTERVAL))

    log.info("Search indexer stopped")


if __name__ == "__main__":
    main()
