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
               s.created_at, s.last_seen_at, s.raw_json
        FROM servers s
        LEFT JOIN projects p ON s.project_id = p.id
        LEFT JOIN domains d ON p.domain_id = d.id
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
        "body_text": " ".join(filter(None, [
            _safe(r["name"]), _safe(r.get("status")),
            _safe(r.get("vm_state")), _safe(r.get("hypervisor_hostname")),
            _safe(r.get("project_name")), _safe(r.get("domain_name")),
            _safe(r.get("flavor_id")),
            _json_extract(r.get("raw_json"), "OS-EXT-SRV-ATTR:host",
                          "OS-EXT-STS:task_state", "key_name",
                          "accessIPv4", "accessIPv6"),
        ])),
        "ts": r.get("last_seen_at") or r.get("created_at"),
        "metadata": _metadata(r),
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
        "body_text": " ".join(filter(None, [
            _safe(r.get("name")), _safe(r.get("status")),
            _safe(r.get("volume_type")), _safe(r.get("project_name")),
            _safe(r.get("domain_name")),
            f"{r.get('size_gb', '')}GB" if r.get("size_gb") else "",
            "bootable" if r.get("bootable") else "",
        ])),
        "ts": r.get("last_seen_at") or r.get("created_at"),
        "metadata": _metadata(r, "volume_type", "bootable"),
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
        "body_text": " ".join(filter(None, [
            _safe(r.get("name")), _safe(r.get("description")),
            _safe(r.get("status")), _safe(r.get("project_name")),
            _safe(r.get("tenant_name")), _safe(r.get("domain_name")),
            _safe(r.get("volume_id")),
        ])),
        "ts": r.get("last_seen_at") or r.get("created_at"),
        "metadata": _metadata(r),
    }))

    # ── Hypervisors ──────────────────────────────────────────
    indexers.append(("hypervisor", """
        SELECT id, hostname, hypervisor_type, vcpus, memory_mb,
               local_gb, state, status, last_seen_at
        FROM hypervisors
        WHERE last_seen_at > %s
        ORDER BY last_seen_at
    """, lambda r: {
        "resource_id": r["id"],
        "resource_name": r.get("hostname"),
        "tenant_id": None, "tenant_name": "",
        "domain_id": None, "domain_name": "",
        "title": f"Hypervisor: {_safe(r.get('hostname'))} ({_safe(r.get('state'))})",
        "body_text": " ".join(filter(None, [
            _safe(r.get("hostname")), _safe(r.get("hypervisor_type")),
            _safe(r.get("state")), _safe(r.get("status")),
            f"{r.get('vcpus', '')} vCPUs" if r.get("vcpus") else "",
            f"{r.get('memory_mb', '')}MB RAM" if r.get("memory_mb") else "",
        ])),
        "ts": r.get("last_seen_at"),
        "metadata": _metadata(r, "hypervisor_type", "vcpus", "memory_mb", "local_gb"),
    }))

    # ── Networks ─────────────────────────────────────────────
    indexers.append(("network", """
        SELECT n.id, n.name, n.project_id, p.name AS project_name,
               d.name AS domain_name, d.id AS domain_id,
               n.is_shared, n.is_external, n.last_seen_at
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
        "body_text": " ".join(filter(None, [
            _safe(r.get("name")), _safe(r.get("project_name")),
            "shared" if r.get("is_shared") else "",
            "external" if r.get("is_external") else "",
        ])),
        "ts": r.get("last_seen_at"),
        "metadata": {"is_shared": r.get("is_shared"), "is_external": r.get("is_external")},
    }))

    # ── Subnets ──────────────────────────────────────────────
    indexers.append(("subnet", """
        SELECT s.id, s.name, s.network_id, s.cidr, s.gateway_ip,
               s.last_seen_at
        FROM subnets s
        WHERE s.last_seen_at > %s
        ORDER BY s.last_seen_at
    """, lambda r: {
        "resource_id": r["id"],
        "resource_name": _safe(r.get("name")),
        "tenant_id": None, "tenant_name": "",
        "domain_id": None, "domain_name": "",
        "title": f"Subnet: {_safe(r.get('name'))} ({_safe(r.get('cidr'))})",
        "body_text": " ".join(filter(None, [
            _safe(r.get("name")), _safe(r.get("cidr")),
            _safe(r.get("gateway_ip")), _safe(r.get("network_id")),
        ])),
        "ts": r.get("last_seen_at"),
        "metadata": {"cidr": r.get("cidr"), "gateway_ip": r.get("gateway_ip")},
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
        "body_text": " ".join(filter(None, [
            _safe(r.get("floating_ip")), _safe(r.get("fixed_ip")),
            _safe(r.get("status")), _safe(r.get("project_name")),
            _safe(r.get("port_id")),
        ])),
        "ts": r.get("last_seen_at"),
        "metadata": _metadata(r),
    }))

    # ── Ports ────────────────────────────────────────────────
    indexers.append(("port", """
        SELECT po.id, po.name, po.network_id, po.project_id,
               po.device_id, po.device_owner, po.mac_address,
               po.ip_addresses, po.last_seen_at,
               p.name AS project_name,
               d.name AS domain_name, d.id AS domain_id
        FROM ports po
        LEFT JOIN projects p ON po.project_id = p.id
        LEFT JOIN domains d ON p.domain_id = d.id
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
        "body_text": " ".join(filter(None, [
            _safe(r.get("name")), _safe(r.get("mac_address")),
            _safe(r.get("device_id")), _safe(r.get("device_owner")),
            _safe(r.get("project_name")),
            json.dumps(r["ip_addresses"]) if r.get("ip_addresses") else "",
        ])),
        "ts": r.get("last_seen_at"),
        "metadata": {"device_owner": r.get("device_owner")},
    }))

    # ── Security Groups ──────────────────────────────────────
    indexers.append(("security_group", """
        SELECT id, name, description, project_id, project_name,
               tenant_name, domain_id, domain_name,
               created_at, updated_at
        FROM security_groups
        WHERE COALESCE(updated_at, created_at) > %s
        ORDER BY COALESCE(updated_at, created_at)
    """, lambda r: {
        "resource_id": r["id"],
        "resource_name": _safe(r.get("name")),
        "tenant_id": r.get("project_id"),
        "tenant_name": _safe(r.get("tenant_name") or r.get("project_name")),
        "domain_id": _safe(r.get("domain_id")),
        "domain_name": _safe(r.get("domain_name")),
        "title": f"Security Group: {_safe(r.get('name'))}",
        "body_text": " ".join(filter(None, [
            _safe(r.get("name")), _safe(r.get("description")),
            _safe(r.get("project_name")), _safe(r.get("domain_name")),
        ])),
        "ts": r.get("updated_at") or r.get("created_at"),
        "metadata": {},
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
        "body_text": " ".join(filter(None, [
            _safe(r.get("actor")), _safe(r.get("action")),
            _safe(r.get("resource_type")), _safe(r.get("resource_id")),
            _safe(r.get("resource_name")), _safe(r.get("domain_name")),
            _safe(r.get("result")), _safe(r.get("error_message")),
            _safe(r.get("ip_address")),
            json.dumps(r["details"]) if r.get("details") else "",
        ])),
        "ts": r.get("timestamp"),
        "metadata": _metadata(r, "resource_type", "result"),
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
        "body_text": " ".join(filter(None, [
            _safe(r.get("username")), _safe(r.get("action")),
            _safe(r.get("resource")), _safe(r.get("endpoint")),
            str(r.get("ip_address", "")),
            "success" if r.get("success") else "failed",
            json.dumps(r["details"]) if r.get("details") else "",
        ])),
        "ts": r.get("timestamp"),
        "metadata": {"success": r.get("success"), "action": r.get("action")},
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
        "body_text": " ".join(filter(None, [
            _safe(r.get("resource_type")), _safe(r.get("resource_name")),
            _safe(r.get("field_changed")),
            f"old:{_safe(r.get('old_value'))}", f"new:{_safe(r.get('new_value'))}",
            _safe(r.get("description")), _safe(r.get("severity")),
            _safe(r.get("project_name")), _safe(r.get("domain_name")),
        ])),
        "ts": r.get("detected_at"),
        "metadata": _metadata(r, "field_changed", "old_value", "new_value", "acknowledged"),
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
        "body_text": " ".join(filter(None, [
            _safe(r.get("run_type")), _safe(r.get("status")),
            _safe(r.get("triggered_by")), _safe(r.get("trigger_source")),
            _safe(r.get("error_summary")),
            f"{r.get('total_volumes', 0)} volumes",
            f"{r.get('snapshots_created', 0)} created",
            f"{r.get('snapshots_failed', 0)} failed",
        ])),
        "ts": r.get("started_at"),
        "metadata": _metadata(r, "snapshots_created", "snapshots_failed", "total_volumes"),
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
        "body_text": " ".join(filter(None, [
            _safe(r.get("action")), _safe(r.get("snapshot_name")),
            _safe(r.get("volume_name")), _safe(r.get("vm_name")),
            _safe(r.get("tenant_name")), _safe(r.get("project_name")),
            _safe(r.get("policy_name")), _safe(r.get("status")),
            _safe(r.get("error_message")),
        ])),
        "ts": datetime.now(timezone.utc),  # no timestamp column
        "metadata": _metadata(r, "policy_name", "volume_id", "vm_id"),
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
        "body_text": " ".join(filter(None, [
            _safe(r.get("vm_name")), _safe(r.get("requested_name")),
            _safe(r.get("mode")), _safe(r.get("status")),
            _safe(r.get("created_by")), _safe(r.get("project_name")),
            _safe(r.get("restore_point_name")),
            _safe(r.get("failure_reason")),
        ])),
        "ts": r.get("created_at"),
        "metadata": _metadata(r, "mode", "failure_reason"),
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
        "body_text": " ".join(filter(None, [
            _safe(r.get("backup_type")), _safe(r.get("backup_target")),
            _safe(r.get("status")), _safe(r.get("file_name")),
            _safe(r.get("initiated_by")), _safe(r.get("error_message")),
        ])),
        "ts": r.get("started_at"),
        "metadata": _metadata(r, "file_size_bytes", "duration_seconds"),
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
        "body_text": " ".join(filter(None, [
            _safe(r.get("username")), _safe(r.get("event_type")),
            _safe(r.get("subject")), _safe(r.get("body_preview")),
            _safe(r.get("delivery_status")), _safe(r.get("error_message")),
        ])),
        "ts": r.get("sent_at") or r.get("created_at"),
        "metadata": {"event_type": r.get("event_type"), "delivery_status": r.get("delivery_status")},
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
        "body_text": " ".join(filter(None, [
            _safe(r.get("domain_name")), _safe(r.get("project_name")),
            _safe(r.get("username")), _safe(r.get("user_email")),
            _safe(r.get("status")), _safe(r.get("error_message")),
            _safe(r.get("network_name")), _safe(r.get("subnet_cidr")),
            _safe(r.get("created_by")),
        ])),
        "ts": r.get("created_at"),
        "metadata": _metadata(r, "network_type"),
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
        "body_text": " ".join(filter(None, [
            "deleted", _safe(r.get("resource_type")),
            _safe(r.get("resource_name")), _safe(r.get("resource_id")),
            _safe(r.get("project_name")), _safe(r.get("domain_name")),
            _safe(r.get("reason")),
        ])),
        "ts": r.get("deleted_at"),
        "metadata": {"resource_type": r.get("resource_type"), "reason": r.get("reason")},
    }))

    return indexers


# ── Main indexing logic ──────────────────────────────────────

# snapshot_record uses id-based watermark, not timestamp
ID_BASED_TYPES = {"snapshot_record"}

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

        conn.close()
    except Exception as e:
        log.error("Indexing cycle failed: %s", e)

    duration = time.time() - total_start
    log.info("Indexing cycle complete: %d documents in %.1fs", total_indexed, duration)
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
