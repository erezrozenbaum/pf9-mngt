"""
Runbook Routes — Policy-as-Code operational runbooks with flexible approval workflows.

Provides:
- CRUD for runbook definitions and approval policies
- Trigger / approve / reject / cancel execution workflow
- Built-in execution engines for Stuck VM and Orphan Cleanup
- Full audit trail for all executions
"""

import os
import json
import logging
import traceback
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Request, status, Query
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from db_pool import get_connection
from auth import require_permission, get_current_user

logger = logging.getLogger("pf9_runbooks")

router = APIRouter(prefix="/api/runbooks", tags=["runbooks"])


# ---------------------------------------------------------------------------
#  Auto-migration on import
# ---------------------------------------------------------------------------
def _ensure_tables():
    """Run migration if tables don't exist yet."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'runbooks'
                    )
                """)
                if not cur.fetchone()[0]:
                    migration = os.path.join(
                        os.path.dirname(__file__), "..", "db", "migrate_runbooks.sql"
                    )
                    if os.path.exists(migration):
                        with open(migration) as f:
                            cur.execute(f.read())
                        conn.commit()
                        logger.info("Runbook tables created via auto-migration")
    except Exception as e:
        logger.warning(f"Could not ensure runbook tables on startup: {e}")


try:
    _ensure_tables()
except Exception:
    pass


# ---------------------------------------------------------------------------
#  Pydantic models
# ---------------------------------------------------------------------------
class TriggerRunbookRequest(BaseModel):
    runbook_name: str
    dry_run: bool = True
    parameters: dict = Field(default_factory=dict)


class ApproveRejectRequest(BaseModel):
    decision: str  # "approved" or "rejected"
    comment: str = ""


class ApprovalPolicyUpdate(BaseModel):
    trigger_role: str
    approver_role: str
    approval_mode: str = "single_approval"
    escalation_timeout_minutes: int = 60
    max_auto_executions_per_day: int = 50
    enabled: bool = True


# ---------------------------------------------------------------------------
#  Helper — fire_notification (import from provisioning_routes)
# ---------------------------------------------------------------------------
def _notify(event_type: str, summary: str, severity: str = "info", **kw):
    """Thin wrapper to fire notifications without crashing if the helper is unavailable."""
    try:
        from provisioning_routes import _fire_notification
        _fire_notification(event_type=event_type, summary=summary, severity=severity, **kw)
    except Exception as e:
        logger.warning(f"Notification failed: {e}")


# ---------------------------------------------------------------------------
#  Runbook execution engines (pluggable)
# ---------------------------------------------------------------------------
RUNBOOK_ENGINES: Dict[str, Any] = {}  # populated below


def register_engine(name: str):
    """Decorator to register a runbook execution engine."""
    def decorator(fn):
        RUNBOOK_ENGINES[name] = fn
        return fn
    return decorator


def _resolve_project_names(client, headers) -> Dict[str, str]:
    """Build a project_id → project_name lookup from Keystone."""
    try:
        url = f"{client.keystone_endpoint}/projects"
        resp = client.session.get(url, headers=headers)
        resp.raise_for_status()
        return {p["id"]: p.get("name", p["id"]) for p in resp.json().get("projects", [])}
    except Exception as e:
        logger.warning(f"Could not resolve project names: {e}")
        return {}


def _load_metering_pricing() -> dict:
    """Load pricing and currency from metering_pricing table (flavor-level),
    falling back to metering_config, then hardcoded defaults.
    Returns dict with convenience monthly rates and currency.
    """
    defaults = {
        "cost_per_vcpu_hour": 0.0208,       # ~15/mo
        "cost_per_gb_ram_hour": 0.0069,      # ~5/mo
        "cost_per_gb_storage_month": 2.0,
        "cost_per_snapshot_gb_month": 1.5,
        "cost_per_floating_ip_month": 5.0,
        "cost_currency": "USD",
    }
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1) Try metering_pricing table first (has real per-flavor pricing)
                cur.execute("""
                    SELECT currency,
                           AVG(CASE WHEN vcpus > 0 THEN cost_per_month / vcpus END) AS avg_per_vcpu_month,
                           AVG(CASE WHEN ram_gb > 0 THEN cost_per_month / (vcpus + ram_gb) END) AS avg_blended,
                           AVG(CASE WHEN ram_gb > 0 THEN (cost_per_month - COALESCE(disk_cost_per_gb,0) * disk_gb)
                                / NULLIF(vcpus + ram_gb, 0) END) AS avg_unit
                    FROM metering_pricing
                    WHERE category = 'flavor' AND cost_per_month > 0
                    GROUP BY currency
                    ORDER BY COUNT(*) DESC
                    LIMIT 1
                """)
                flavor_row = cur.fetchone()

                # Storage pricing
                cur.execute("SELECT cost_per_month, currency FROM metering_pricing WHERE category = 'storage_gb' LIMIT 1")
                storage_row = cur.fetchone()

                # Floating IP pricing
                cur.execute("SELECT cost_per_month, currency FROM metering_pricing WHERE category = 'public_ip' LIMIT 1")
                fip_row = cur.fetchone()

                # Snapshot pricing
                cur.execute("SELECT cost_per_month, currency FROM metering_pricing WHERE category = 'snapshot_gb' LIMIT 1")
                snap_row = cur.fetchone()

                # Determine currency from the dominant source
                currency = (
                    (flavor_row or {}).get("currency")
                    or (storage_row or {}).get("currency")
                    or None
                )

                if currency and flavor_row:
                    # Derive per-vCPU and per-GB-RAM from smallest flavors
                    cur.execute("""
                        SELECT vcpus, ram_gb, cost_per_month
                        FROM metering_pricing
                        WHERE category = 'flavor' AND vcpus > 0 AND cost_per_month > 0
                          AND currency = %s
                        ORDER BY vcpus, ram_gb
                        LIMIT 5
                    """, (currency,))
                    small_flavors = cur.fetchall()
                    if len(small_flavors) >= 2:
                        # Use smallest 1-vCPU flavor to estimate per-vCPU cost
                        f1 = small_flavors[0]
                        f2 = small_flavors[1]
                        # Solve: cost = a*vcpus + b*ram_gb
                        v1, r1, c1 = f1["vcpus"], float(f1["ram_gb"]), float(f1["cost_per_month"])
                        v2, r2, c2 = f2["vcpus"], float(f2["ram_gb"]), float(f2["cost_per_month"])
                        det = v1 * r2 - v2 * r1
                        if det != 0:
                            price_vcpu_mo = round((c1 * r2 - c2 * r1) / det, 2)
                            price_ram_mo = round((v1 * c2 - v2 * c1) / det, 2)
                            if price_vcpu_mo <= 0:
                                price_vcpu_mo = round(c1 / max(v1, 1), 2)
                            if price_ram_mo <= 0:
                                price_ram_mo = round((c1 - price_vcpu_mo * v1) / max(r1, 1), 2)
                        else:
                            price_vcpu_mo = round(c1 / max(v1, 1), 2)
                            price_ram_mo = round(price_vcpu_mo * 0.3, 2)
                    elif small_flavors:
                        f1 = small_flavors[0]
                        price_vcpu_mo = round(float(f1["cost_per_month"]) / max(f1["vcpus"], 1), 2)
                        price_ram_mo = round(price_vcpu_mo * 0.3, 2)
                    else:
                        price_vcpu_mo = defaults["cost_per_vcpu_hour"] * 730
                        price_ram_mo = defaults["cost_per_gb_ram_hour"] * 730

                    return {
                        "cost_currency": currency,
                        "price_per_vcpu_month": price_vcpu_mo,
                        "price_per_gb_ram_month": price_ram_mo,
                        "price_per_gb_volume_month": float((storage_row or {}).get("cost_per_month", 0) or 0) or defaults["cost_per_gb_storage_month"],
                        "cost_per_floating_ip_month": float((fip_row or {}).get("cost_per_month", 0) or 0) or defaults["cost_per_floating_ip_month"],
                        "cost_per_snapshot_gb_month": float((snap_row or {}).get("cost_per_month", 0) or 0) or defaults["cost_per_snapshot_gb_month"],
                    }

                # 2) Fallback: metering_config
                cur.execute("SELECT * FROM metering_config WHERE id = 1")
                cfg = cur.fetchone()
                if cfg:
                    hourly_vcpu = float(cfg.get("cost_per_vcpu_hour", 0) or 0)
                    hourly_ram = float(cfg.get("cost_per_gb_ram_hour", 0) or 0)
                    storage_m = float(cfg.get("cost_per_gb_storage_month", 0) or 0)
                    cfg_currency = cfg.get("cost_currency", "USD") or "USD"
                    return {
                        "cost_currency": cfg_currency,
                        "price_per_vcpu_month": round(hourly_vcpu * 730, 2) if hourly_vcpu else defaults["cost_per_vcpu_hour"] * 730,
                        "price_per_gb_ram_month": round(hourly_ram * 730, 2) if hourly_ram else defaults["cost_per_gb_ram_hour"] * 730,
                        "price_per_gb_volume_month": storage_m if storage_m else defaults["cost_per_gb_storage_month"],
                        "cost_per_floating_ip_month": defaults["cost_per_floating_ip_month"],
                        "cost_per_snapshot_gb_month": defaults["cost_per_snapshot_gb_month"],
                    }
    except Exception as e:
        logger.warning(f"Could not load metering pricing: {e}")
    # 3) Hardcoded fallback
    return {
        "cost_currency": defaults["cost_currency"],
        "price_per_vcpu_month": round(defaults["cost_per_vcpu_hour"] * 730, 2),
        "price_per_gb_ram_month": round(defaults["cost_per_gb_ram_hour"] * 730, 2),
        "price_per_gb_volume_month": defaults["cost_per_gb_storage_month"],
        "cost_per_floating_ip_month": defaults["cost_per_floating_ip_month"],
        "cost_per_snapshot_gb_month": defaults["cost_per_snapshot_gb_month"],
    }


# ===== Engine: stuck_vm_remediation =======================================

@register_engine("stuck_vm_remediation")
def _engine_stuck_vm(params: dict, dry_run: bool, actor: str) -> dict:
    """Find and optionally remediate VMs stuck in BUILD/ERROR/transitional states."""
    from pf9_control import get_client

    threshold_minutes = params.get("stuck_threshold_minutes", 30)
    action = params.get("action", "report_only")
    target_project = params.get("target_project", "")
    target_domain = params.get("target_domain", "")

    client = get_client()
    client.authenticate()
    headers = {"X-Auth-Token": client.token}
    project_names = _resolve_project_names(client, headers)

    stuck_states = {"BUILD", "ERROR", "MIGRATING", "RESIZE", "VERIFY_RESIZE",
                    "REVERT_RESIZE", "PAUSED", "SUSPENDED", "SHELVED",
                    "SHELVED_OFFLOADED"}

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=threshold_minutes)

    # Get servers — optionally filter by project
    url = f"{client.nova_endpoint}/servers/detail?all_tenants=true&limit=1000"
    resp = client.session.get(url, headers=headers)
    resp.raise_for_status()
    all_servers = resp.json().get("servers", [])

    stuck_vms = []
    for s in all_servers:
        vm_status = (s.get("status") or "").upper()
        task_state = s.get("OS-EXT-STS:task_state")
        if vm_status not in stuck_states and not task_state:
            continue

        # Check age — updated_at or created for build
        updated = s.get("updated", s.get("created", ""))
        if updated:
            try:
                ts = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                if ts > cutoff:
                    continue  # Not stuck long enough
            except Exception:
                pass

        # Optional project/domain filter
        tenant_id = s.get("tenant_id", "")
        if target_project and tenant_id != target_project:
            continue

        stuck_vms.append({
            "vm_id": s.get("id"),
            "vm_name": s.get("name"),
            "status": vm_status,
            "task_state": task_state,
            "tenant_id": tenant_id,
            "tenant_name": project_names.get(tenant_id, tenant_id),
            "host": s.get("OS-EXT-SRV-ATTR:host", ""),
            "updated": updated,
        })

    result = {
        "stuck_vms": stuck_vms,
        "threshold_minutes": threshold_minutes,
        "action": action if not dry_run else "report_only (dry-run)",
        "remediated": [],
        "errors": [],
    }

    items_found = len(stuck_vms)
    items_actioned = 0

    # Remediate if not dry-run
    if not dry_run and action != "report_only" and stuck_vms:
        for vm in stuck_vms:
            try:
                reboot_type = "SOFT" if action == "soft_reboot" else "HARD"
                reboot_url = f"{client.nova_endpoint}/servers/{vm['vm_id']}/action"
                r = client.session.post(
                    reboot_url, headers=headers,
                    json={"reboot": {"type": reboot_type}}
                )
                if r.status_code < 300:
                    result["remediated"].append({
                        "vm_id": vm["vm_id"], "vm_name": vm["vm_name"],
                        "action": action, "status": "success"
                    })
                    items_actioned += 1
                else:
                    result["errors"].append({
                        "vm_id": vm["vm_id"], "vm_name": vm["vm_name"],
                        "error": f"HTTP {r.status_code}: {r.text[:200]}"
                    })
            except Exception as e:
                result["errors"].append({
                    "vm_id": vm["vm_id"], "vm_name": vm["vm_name"],
                    "error": str(e)
                })

    return {
        "result": result,
        "items_found": items_found,
        "items_actioned": items_actioned,
    }


# ===== Engine: orphan_resource_cleanup ====================================

@register_engine("orphan_resource_cleanup")
def _engine_orphan_cleanup(params: dict, dry_run: bool, actor: str) -> dict:
    """Find and optionally delete orphaned ports, volumes, and floating IPs."""
    from pf9_control import get_client

    resource_types = params.get("resource_types", ["ports", "volumes", "floating_ips"])
    age_days = params.get("age_threshold_days", 7)
    target_project = params.get("target_project", "")

    client = get_client()
    client.authenticate()
    headers = {"X-Auth-Token": client.token}
    project_names = _resolve_project_names(client, headers)

    cutoff = datetime.now(timezone.utc) - timedelta(days=age_days)
    result: Dict[str, Any] = {"orphans": {}, "deleted": {}, "errors": {}}
    total_found = 0
    total_actioned = 0

    # --- Orphan Ports ---
    if "ports" in resource_types:
        url = f"{client.neutron_endpoint}/v2.0/ports"
        resp = client.session.get(url, headers=headers)
        resp.raise_for_status()
        ports = resp.json().get("ports", [])

        orphan_ports = []
        for p in ports:
            device_owner = p.get("device_owner", "")
            device_id = p.get("device_id", "")
            if device_owner or device_id:
                continue  # Not orphaned
            # Check age
            created = p.get("created_at", "")
            if created:
                try:
                    ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if ts > cutoff:
                        continue
                except Exception:
                    pass
            if target_project and p.get("project_id", "") != target_project:
                continue
            pid = p.get("project_id", "")
            orphan_ports.append({
                "port_id": p["id"],
                "port_name": p.get("name", ""),
                "network_id": p.get("network_id"),
                "project_id": pid,
                "project_name": project_names.get(pid, pid),
                "mac_address": p.get("mac_address", ""),
                "created_at": created,
            })

        result["orphans"]["ports"] = orphan_ports
        total_found += len(orphan_ports)

        if not dry_run and orphan_ports:
            deleted = []
            errors = []
            for op in orphan_ports:
                try:
                    r = client.session.delete(
                        f"{client.neutron_endpoint}/v2.0/ports/{op['port_id']}",
                        headers=headers
                    )
                    if r.status_code < 300:
                        deleted.append(op["port_id"])
                        total_actioned += 1
                    else:
                        errors.append({"port_id": op["port_id"], "error": f"HTTP {r.status_code}"})
                except Exception as e:
                    errors.append({"port_id": op["port_id"], "error": str(e)})
            result["deleted"]["ports"] = deleted
            result["errors"]["ports"] = errors

    # --- Orphan Volumes ---
    if "volumes" in resource_types:
        url = f"{client.cinder_endpoint}/volumes/detail?all_tenants=true"
        resp = client.session.get(url, headers=headers)
        resp.raise_for_status()
        volumes = resp.json().get("volumes", [])

        orphan_volumes = []
        for v in volumes:
            if v.get("status") != "available":
                continue
            if v.get("attachments"):
                continue
            created = v.get("created_at", "")
            if created:
                try:
                    ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if ts > cutoff:
                        continue
                except Exception:
                    pass
            tenant_id = v.get("os-vol-tenant-attr:tenant_id", "")
            if target_project and tenant_id != target_project:
                continue
            orphan_volumes.append({
                "volume_id": v["id"],
                "name": v.get("name", "") or v["id"][:8],
                "size_gb": v.get("size", 0),
                "project_id": tenant_id,
                "project_name": project_names.get(tenant_id, tenant_id),
                "created_at": created,
            })

        result["orphans"]["volumes"] = orphan_volumes
        total_found += len(orphan_volumes)

        if not dry_run and orphan_volumes:
            deleted = []
            errors = []
            for ov in orphan_volumes:
                try:
                    r = client.session.delete(
                        f"{client.cinder_endpoint}/volumes/{ov['volume_id']}",
                        headers=headers
                    )
                    if r.status_code < 300:
                        deleted.append(ov["volume_id"])
                        total_actioned += 1
                    else:
                        errors.append({"volume_id": ov["volume_id"], "error": f"HTTP {r.status_code}"})
                except Exception as e:
                    errors.append({"volume_id": ov["volume_id"], "error": str(e)})
            result["deleted"]["volumes"] = deleted
            result["errors"]["volumes"] = errors

    # --- Orphan Floating IPs ---
    if "floating_ips" in resource_types:
        url = f"{client.neutron_endpoint}/v2.0/floatingips"
        resp = client.session.get(url, headers=headers)
        resp.raise_for_status()
        fips = resp.json().get("floatingips", [])

        orphan_fips = []
        for f in fips:
            if f.get("port_id"):
                continue  # Associated
            created = f.get("created_at", "")
            if created:
                try:
                    ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if ts > cutoff:
                        continue
                except Exception:
                    pass
            if target_project and f.get("project_id", "") != target_project:
                continue
            fip_pid = f.get("project_id", "")
            orphan_fips.append({
                "fip_id": f["id"],
                "floating_ip_address": f.get("floating_ip_address", ""),
                "project_id": fip_pid,
                "project_name": project_names.get(fip_pid, fip_pid),
                "created_at": created,
            })

        result["orphans"]["floating_ips"] = orphan_fips
        total_found += len(orphan_fips)

        if not dry_run and orphan_fips:
            deleted = []
            errors = []
            for of_ in orphan_fips:
                try:
                    r = client.session.delete(
                        f"{client.neutron_endpoint}/v2.0/floatingips/{of_['fip_id']}",
                        headers=headers
                    )
                    if r.status_code < 300:
                        deleted.append(of_["fip_id"])
                        total_actioned += 1
                    else:
                        errors.append({"fip_id": of_["fip_id"], "error": f"HTTP {r.status_code}"})
                except Exception as e:
                    errors.append({"fip_id": of_["fip_id"], "error": str(e)})
            result["deleted"]["floating_ips"] = deleted
            result["errors"]["floating_ips"] = errors

    return {
        "result": result,
        "items_found": total_found,
        "items_actioned": total_actioned,
    }


# ===== Engine: security_group_audit =======================================

@register_engine("security_group_audit")
def _engine_sg_audit(params: dict, dry_run: bool, actor: str) -> dict:
    """Scan security groups for overly permissive rules."""
    from pf9_control import get_client

    flag_ports = params.get("flag_ports", [22, 3389, 3306, 5432, 1433, 27017])
    target_project = params.get("target_project", "")

    client = get_client()
    client.authenticate()
    headers = {"X-Auth-Token": client.token}
    project_names = _resolve_project_names(client, headers)

    url = f"{client.neutron_endpoint}/v2.0/security-groups"
    resp = client.session.get(url, headers=headers)
    resp.raise_for_status()
    sgs = resp.json().get("security_groups", [])

    violations = []
    for sg in sgs:
        if target_project and sg.get("project_id", "") != target_project:
            continue
        for rule in sg.get("security_group_rules", []):
            if rule.get("direction") != "ingress":
                continue
            remote = rule.get("remote_ip_prefix") or ""
            if remote not in ("0.0.0.0/0", "::/0"):
                continue
            port_min = rule.get("port_range_min")
            port_max = rule.get("port_range_max")
            # Check if any flagged port falls within the range
            flagged = []
            for fp in flag_ports:
                if port_min is None and port_max is None:
                    flagged.append(fp)  # All ports open
                elif port_min is not None and port_max is not None:
                    if port_min <= fp <= port_max:
                        flagged.append(fp)
            if flagged:
                sg_pid = sg.get("project_id", "")
                violations.append({
                    "sg_id": sg["id"],
                    "sg_name": sg.get("name", ""),
                    "project_id": sg_pid,
                    "project_name": project_names.get(sg_pid, sg_pid),
                    "rule_id": rule.get("id", ""),
                    "protocol": rule.get("protocol", "any"),
                    "port_range": f"{port_min}-{port_max}" if port_min else "all",
                    "remote_ip_prefix": remote,
                    "flagged_ports": flagged,
                    "description": rule.get("description", ""),
                })

    return {
        "result": {"violations": violations},
        "items_found": len(violations),
        "items_actioned": 0,  # audit is read-only
    }


# ===== Engine: quota_threshold_check ======================================

@register_engine("quota_threshold_check")
def _engine_quota_check(params: dict, dry_run: bool, actor: str) -> dict:
    """Check quota utilisation across projects."""
    from pf9_control import get_client

    warning_pct = params.get("warning_pct", 80)
    critical_pct = params.get("critical_pct", 95)
    target_project = params.get("target_project", "")

    client = get_client()
    client.authenticate()
    headers = {"X-Auth-Token": client.token}

    # Get all projects
    ks_url = f"{client.keystone_endpoint}/projects"
    resp = client.session.get(ks_url, headers=headers)
    resp.raise_for_status()
    projects = resp.json().get("projects", [])

    if target_project:
        projects = [p for p in projects if p["id"] == target_project or p.get("name") == target_project]

    alerts = []
    for proj in projects:
        pid = proj["id"]
        pname = proj.get("name", pid)

        # Compute quotas
        try:
            q_url = f"{client.nova_endpoint}/os-quota-sets/{pid}/detail"
            qr = client.session.get(q_url, headers=headers)
            if qr.status_code == 200:
                qs = qr.json().get("quota_set", {})
                for metric in ["cores", "ram", "instances"]:
                    data = qs.get(metric, {})
                    limit = data.get("limit", -1)
                    in_use = data.get("in_use", 0)
                    if limit > 0:
                        pct = round(in_use / limit * 100, 1)
                        level = "critical" if pct >= critical_pct else "warning" if pct >= warning_pct else None
                        if level:
                            alerts.append({
                                "project_id": pid,
                                "project_name": pname,
                                "resource": f"compute.{metric}",
                                "in_use": in_use,
                                "limit": limit,
                                "utilisation_pct": pct,
                                "level": level,
                            })
        except Exception as e:
            logger.warning(f"Quota check failed for project {pname}: {e}")

    return {
        "result": {"alerts": alerts, "warning_pct": warning_pct, "critical_pct": critical_pct},
        "items_found": len(alerts),
        "items_actioned": 0,
    }


# ===== Engine: diagnostics_bundle =========================================

@register_engine("diagnostics_bundle")
def _engine_diagnostics(params: dict, dry_run: bool, actor: str) -> dict:
    """Collect a diagnostics bundle for incident triage."""
    from pf9_control import get_client

    sections = params.get("include_sections", ["hypervisors", "services", "resources", "quotas"])

    client = get_client()
    client.authenticate()
    headers = {"X-Auth-Token": client.token}

    bundle: Dict[str, Any] = {"collected_at": datetime.now(timezone.utc).isoformat()}

    if "hypervisors" in sections:
        try:
            url = f"{client.nova_endpoint}/os-hypervisors/detail"
            r = client.session.get(url, headers=headers)
            r.raise_for_status()
            hvs = r.json().get("hypervisors", [])
            bundle["hypervisors"] = [{
                "id": h.get("id"),
                "hostname": h.get("hypervisor_hostname"),
                "status": h.get("status"),
                "state": h.get("state"),
                "vcpus_used": h.get("vcpus_used", 0),
                "vcpus_total": h.get("vcpus", 0),
                "memory_used_mb": h.get("memory_mb_used", 0),
                "memory_total_mb": h.get("memory_mb", 0),
                "running_vms": h.get("running_vms", 0),
                "hypervisor_type": h.get("hypervisor_type", ""),
            } for h in hvs]
        except Exception as e:
            bundle["hypervisors_error"] = str(e)

    if "services" in sections:
        try:
            url = f"{client.nova_endpoint}/os-services"
            r = client.session.get(url, headers=headers)
            r.raise_for_status()
            svcs = r.json().get("services", [])
            bundle["services"] = [{
                "binary": s.get("binary"),
                "host": s.get("host"),
                "zone": s.get("zone"),
                "status": s.get("status"),
                "state": s.get("state"),
                "updated_at": s.get("updated_at"),
            } for s in svcs]
        except Exception as e:
            bundle["services_error"] = str(e)

    if "resources" in sections:
        try:
            counts = {}
            # Servers
            r = client.session.get(f"{client.nova_endpoint}/servers/detail?all_tenants=true&limit=1", headers=headers)
            if r.status_code == 200:
                counts["servers_sample"] = len(r.json().get("servers", []))
            # Networks
            r = client.session.get(f"{client.neutron_endpoint}/v2.0/networks", headers=headers)
            if r.status_code == 200:
                counts["networks"] = len(r.json().get("networks", []))
            # Volumes
            r = client.session.get(f"{client.cinder_endpoint}/volumes/detail?all_tenants=true&limit=1", headers=headers)
            if r.status_code == 200:
                counts["volumes_sample"] = len(r.json().get("volumes", []))
            bundle["resource_counts"] = counts
        except Exception as e:
            bundle["resources_error"] = str(e)

    if "quotas" in sections:
        try:
            # Get default quota
            r = client.session.get(f"{client.nova_endpoint}/os-quota-sets/defaults", headers=headers)
            if r.status_code == 200:
                bundle["default_quotas"] = r.json().get("quota_set", {})
        except Exception as e:
            bundle["quotas_error"] = str(e)

    return {
        "result": bundle,
        "items_found": sum(len(v) for v in bundle.values() if isinstance(v, list)),
        "items_actioned": 0,
    }


# ===== Engine: vm_health_quickfix =========================================

@register_engine("vm_health_quickfix")
def _engine_vm_health(params: dict, dry_run: bool, actor: str) -> dict:
    """Diagnose a VM and optionally restart it."""
    from pf9_control import get_client
    import secrets as _secrets

    server_id = params.get("server_id", "")
    if not server_id:
        return {"result": {"error": "server_id is required"}, "items_found": 0, "items_actioned": 0}

    auto_restart = params.get("auto_restart", False)
    restart_type = params.get("restart_type", "soft")

    client = get_client()
    client.authenticate()
    headers = {"X-Auth-Token": client.token}

    checks: Dict[str, Any] = {}
    issues: list = []

    # 1. Get server detail
    srv_url = f"{client.nova_endpoint}/servers/{server_id}"
    resp = client.session.get(srv_url, headers=headers)
    if resp.status_code != 200:
        return {"result": {"error": f"Server not found: HTTP {resp.status_code}"},
                "items_found": 0, "items_actioned": 0}
    server = resp.json().get("server", {})

    # 2. Power state
    power_state = server.get("OS-EXT-STS:power_state", -1)
    power_map = {0: "NO_STATE", 1: "RUNNING", 3: "PAUSED", 4: "SHUTDOWN", 6: "CRASHED", 7: "SUSPENDED"}
    power_label = power_map.get(power_state, f"UNKNOWN({power_state})")
    vm_status = (server.get("status") or "").upper()
    checks["power_state"] = {"status": power_label, "vm_status": vm_status, "ok": vm_status == "ACTIVE" and power_state == 1}
    if not checks["power_state"]["ok"]:
        issues.append(f"VM status {vm_status}, power state {power_label}")

    # 3. Hypervisor state
    host = server.get("OS-EXT-SRV-ATTR:host", "")
    checks["hypervisor"] = {"host": host, "ok": False, "detail": ""}
    if host:
        try:
            hv_url = f"{client.nova_endpoint}/os-hypervisors/detail"
            hr = client.session.get(hv_url, headers=headers)
            if hr.status_code == 200:
                for hv in hr.json().get("hypervisors", []):
                    if hv.get("hypervisor_hostname") == host or hv.get("service", {}).get("host") == host:
                        hv_state = hv.get("state", "")
                        hv_status = hv.get("status", "")
                        checks["hypervisor"]["state"] = hv_state
                        checks["hypervisor"]["status"] = hv_status
                        checks["hypervisor"]["ok"] = hv_state == "up" and hv_status == "enabled"
                        if not checks["hypervisor"]["ok"]:
                            issues.append(f"Hypervisor {host} is {hv_state}/{hv_status}")
                        break
        except Exception as e:
            checks["hypervisor"]["detail"] = str(e)
    else:
        issues.append("No hypervisor host assigned")

    # 4. Port bindings
    try:
        port_url = f"{client.neutron_endpoint}/v2.0/ports?device_id={server_id}"
        pr = client.session.get(port_url, headers=headers)
        ports = pr.json().get("ports", []) if pr.status_code == 200 else []
        port_details = []
        port_ok = True
        for p in ports:
            binding = p.get("binding:vif_type", "")
            bound = binding not in ("unbound", "binding_failed", "")
            if not bound:
                port_ok = False
            port_details.append({
                "port_id": p["id"][:8],
                "mac": p.get("mac_address", ""),
                "status": p.get("status", ""),
                "binding": binding,
                "ok": bound,
            })
        checks["ports"] = {"count": len(ports), "ok": port_ok and len(ports) > 0, "details": port_details}
        if not checks["ports"]["ok"]:
            issues.append(f"Port binding issues ({len(ports)} ports, binding_ok={port_ok})")
    except Exception as e:
        checks["ports"] = {"ok": False, "error": str(e)}
        issues.append(f"Port check failed: {e}")

    # 5. Attached volumes
    try:
        vol_url = f"{client.nova_endpoint}/servers/{server_id}/os-volume_attachments"
        vr = client.session.get(vol_url, headers=headers)
        attachments = vr.json().get("volumeAttachments", []) if vr.status_code == 200 else []
        checks["volumes"] = {"count": len(attachments), "ok": True, "details": [
            {"volume_id": a.get("volumeId", "")[:8], "device": a.get("device", "")}
            for a in attachments
        ]}
    except Exception as e:
        checks["volumes"] = {"ok": False, "error": str(e)}

    # 6. Network / Security groups / Floating IP
    try:
        sg_names = [sg.get("name", "") for sg in server.get("security_groups", [])]
        addresses = server.get("addresses", {})
        floating_ips = []
        for net_name, addrs in addresses.items():
            for a in addrs:
                if a.get("OS-EXT-IPS:type") == "floating":
                    floating_ips.append(a.get("addr", ""))
        checks["network"] = {
            "security_groups": sg_names,
            "floating_ips": floating_ips,
            "networks": list(addresses.keys()),
            "ok": len(addresses) > 0,
        }
        if not checks["network"]["ok"]:
            issues.append("No network interfaces found")
    except Exception as e:
        checks["network"] = {"ok": False, "error": str(e)}

    # Remediation
    remediation = {"attempted": False, "result": None}
    items_actioned = 0
    if auto_restart and not dry_run and issues:
        remediation["attempted"] = True
        try:
            if vm_status == "ERROR":
                # Reset state first, then reboot
                reset_url = f"{client.nova_endpoint}/servers/{server_id}/action"
                client.session.post(reset_url, headers=headers,
                                    json={"os-resetState": {"state": "active"}})
            reboot_body = {"reboot": {"type": "SOFT" if restart_type == "soft" else "HARD"}}
            if restart_type == "guest_os":
                reboot_body = {"reboot": {"type": "SOFT"}}
            action_url = f"{client.nova_endpoint}/servers/{server_id}/action"
            ar = client.session.post(action_url, headers=headers, json=reboot_body)
            remediation["result"] = "success" if ar.status_code < 300 else f"HTTP {ar.status_code}: {ar.text[:200]}"
            if ar.status_code < 300:
                items_actioned = 1
        except Exception as e:
            remediation["result"] = f"error: {e}"

    overall_ok = all(c.get("ok", False) for c in checks.values())
    return {
        "result": {
            "server_id": server_id,
            "server_name": server.get("name", ""),
            "overall_healthy": overall_ok,
            "issues": issues,
            "checks": checks,
            "remediation": remediation,
        },
        "items_found": len(issues),
        "items_actioned": items_actioned,
    }


# ===== Engine: snapshot_before_escalation =================================

@register_engine("snapshot_before_escalation")
def _engine_snapshot_escalation(params: dict, dry_run: bool, actor: str) -> dict:
    """Create a snapshot tagged for Tier 2 escalation."""
    from pf9_control import get_client

    server_id = params.get("server_id", "")
    if not server_id:
        return {"result": {"error": "server_id is required"}, "items_found": 0, "items_actioned": 0}

    reference_id = params.get("reference_id", "")
    tag_prefix = params.get("tag_prefix", "Pre-T2-escalation")

    client = get_client()
    client.authenticate()
    headers = {"X-Auth-Token": client.token}

    # Get server detail for summary
    srv_url = f"{client.nova_endpoint}/servers/{server_id}"
    resp = client.session.get(srv_url, headers=headers)
    if resp.status_code != 200:
        return {"result": {"error": f"Server not found: HTTP {resp.status_code}"},
                "items_found": 0, "items_actioned": 0}
    server = resp.json().get("server", {})
    vm_name = server.get("name", server_id[:8])

    # Capture VM state summary
    vm_summary = {
        "name": vm_name,
        "status": server.get("status", ""),
        "power_state": server.get("OS-EXT-STS:power_state", ""),
        "host": server.get("OS-EXT-SRV-ATTR:host", ""),
        "addresses": server.get("addresses", {}),
        "security_groups": [sg.get("name", "") for sg in server.get("security_groups", [])],
        "flavor": server.get("flavor", {}).get("id", ""),
        "tenant_id": server.get("tenant_id", ""),
    }

    # Attached volumes
    try:
        vol_url = f"{client.nova_endpoint}/servers/{server_id}/os-volume_attachments"
        vr = client.session.get(vol_url, headers=headers)
        vm_summary["attached_volumes"] = [
            a.get("volumeId", "") for a in vr.json().get("volumeAttachments", [])
        ] if vr.status_code == 200 else []
    except Exception:
        vm_summary["attached_volumes"] = []

    # Console log tail
    try:
        log_url = f"{client.nova_endpoint}/servers/{server_id}/action"
        lr = client.session.post(log_url, headers=headers,
                                 json={"os-getConsoleOutput": {"length": 30}})
        vm_summary["console_log_tail"] = lr.json().get("output", "") if lr.status_code == 200 else ""
    except Exception:
        vm_summary["console_log_tail"] = ""

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    snapshot_name = f"{tag_prefix}_{vm_name}_{ts}"

    metadata = {
        "escalation_tag": tag_prefix,
        "reference_id": reference_id,
        "actor": actor,
        "timestamp": ts,
        "vm_status": vm_summary["status"],
    }

    result: Dict[str, Any] = {
        "server_id": server_id,
        "server_name": vm_name,
        "snapshot_name": snapshot_name,
        "metadata": metadata,
        "vm_summary": vm_summary,
    }

    if dry_run:
        result["action"] = "dry_run — snapshot not created"
        return {"result": result, "items_found": 1, "items_actioned": 0}

    # Create snapshot
    try:
        snap_url = f"{client.nova_endpoint}/servers/{server_id}/action"
        body = {"createImage": {"name": snapshot_name, "metadata": metadata}}
        sr = client.session.post(snap_url, headers=headers, json=body)
        if sr.status_code < 300:
            image_id = sr.headers.get("Location", "").rsplit("/", 1)[-1] or "pending"
            result["snapshot_id"] = image_id
            result["action"] = "snapshot_created"
            return {"result": result, "items_found": 1, "items_actioned": 1}
        else:
            result["action"] = f"failed: HTTP {sr.status_code}"
            result["error"] = sr.text[:300]
            return {"result": result, "items_found": 1, "items_actioned": 0}
    except Exception as e:
        result["action"] = f"error: {e}"
        return {"result": result, "items_found": 1, "items_actioned": 0}


# ===== Engine: upgrade_opportunity_detector ===============================

@register_engine("upgrade_opportunity_detector")
def _engine_upgrade_detector(params: dict, dry_run: bool, actor: str) -> dict:
    """Detect tenants with upgrade or upsell opportunities."""
    from pf9_control import get_client

    quota_threshold = params.get("quota_threshold_pct", 80)
    include_flavor = params.get("include_flavor_analysis", True)
    include_image = params.get("include_image_analysis", True)

    # Load pricing from metering_config
    pricing = _load_metering_pricing()
    price_vcpu = pricing["price_per_vcpu_month"]
    price_gb_ram = pricing["price_per_gb_ram_month"]
    currency = pricing["cost_currency"]

    client = get_client()
    client.authenticate()
    headers = {"X-Auth-Token": client.token}

    # Gather projects
    resp = client.session.get(f"{client.keystone_endpoint}/projects", headers=headers)
    resp.raise_for_status()
    projects = resp.json().get("projects", [])
    project_map = {p["id"]: p.get("name", p["id"]) for p in projects}

    # Gather all servers
    srv_resp = client.session.get(
        f"{client.nova_endpoint}/servers/detail?all_tenants=true&limit=1000", headers=headers)
    all_servers = srv_resp.json().get("servers", []) if srv_resp.status_code == 200 else []

    # Gather all flavors for analysis
    flv_resp = client.session.get(f"{client.nova_endpoint}/flavors/detail", headers=headers)
    all_flavors = flv_resp.json().get("flavors", []) if flv_resp.status_code == 200 else []
    flavor_map = {f["id"]: f for f in all_flavors}
    max_vcpus = max((f.get("vcpus", 0) for f in all_flavors), default=0)
    max_ram = max((f.get("ram", 0) for f in all_flavors), default=0)

    # Gather images for age analysis
    images = []
    if include_image:
        try:
            img_resp = client.session.get(f"{client.glance_endpoint}/v2/images?limit=500", headers=headers)
            images = img_resp.json().get("images", []) if img_resp.status_code == 200 else []
        except Exception:
            pass
    image_map = {i["id"]: i for i in images}
    two_years_ago = datetime.now(timezone.utc) - timedelta(days=730)

    opportunities: list = []
    total_revenue_delta = 0.0

    # Per-tenant analysis
    tenant_servers: Dict[str, list] = {}
    for s in all_servers:
        tid = s.get("tenant_id", "")
        tenant_servers.setdefault(tid, []).append(s)

    for tid, servers in tenant_servers.items():
        tname = project_map.get(tid, tid)
        tenant_opps: list = []

        # Quota pressure
        try:
            q_url = f"{client.nova_endpoint}/os-quota-sets/{tid}/detail"
            qr = client.session.get(q_url, headers=headers)
            if qr.status_code == 200:
                qs = qr.json().get("quota_set", {})
                for metric in ["cores", "ram", "instances"]:
                    d = qs.get(metric, {})
                    lim = d.get("limit", -1)
                    use = d.get("in_use", 0)
                    if lim > 0:
                        pct = round(use / lim * 100, 1)
                        if pct >= quota_threshold:
                            tenant_opps.append({
                                "type": "quota_pressure",
                                "resource": metric,
                                "usage_pct": pct,
                                "in_use": use,
                                "limit": lim,
                                "suggestion": f"Increase {metric} quota (currently {pct}% used)",
                            })
        except Exception:
            pass

        # Old/small flavors
        if include_flavor:
            for s in servers:
                flv_id = s.get("flavor", {}).get("id", "")
                flv = flavor_map.get(flv_id, {})
                vcpus = flv.get("vcpus", 0)
                ram_mb = flv.get("ram", 0)
                if vcpus > 0 and vcpus < 2 and max_vcpus > vcpus:
                    delta = (2 - vcpus) * price_vcpu
                    total_revenue_delta += delta
                    tenant_opps.append({
                        "type": "small_flavor",
                        "vm_name": s.get("name", ""),
                        "vm_id": s.get("id", ""),
                        "current_flavor": flv.get("name", flv_id),
                        "vcpus": vcpus,
                        "ram_mb": ram_mb,
                        "suggestion": f"Upgrade from {vcpus}vCPU to 2+ vCPU",
                        "revenue_delta": delta,
                    })
                if ram_mb > 0 and ram_mb < 2048 and max_ram > ram_mb:
                    delta = ((2048 - ram_mb) / 1024) * price_gb_ram
                    total_revenue_delta += delta
                    tenant_opps.append({
                        "type": "small_ram",
                        "vm_name": s.get("name", ""),
                        "vm_id": s.get("id", ""),
                        "current_flavor": flv.get("name", flv_id),
                        "ram_mb": ram_mb,
                        "suggestion": f"Upgrade from {ram_mb}MB to 2048+ MB RAM",
                        "revenue_delta": delta,
                    })

        # Old images
        if include_image:
            for s in servers:
                img_id = s.get("image", {}).get("id", "")
                img = image_map.get(img_id, {})
                if not img:
                    continue
                img_created = img.get("created_at", "")
                img_status = img.get("status", "active")
                if img_created:
                    try:
                        ts = datetime.fromisoformat(img_created.replace("Z", "+00:00"))
                        if ts < two_years_ago:
                            tenant_opps.append({
                                "type": "old_image",
                                "vm_name": s.get("name", ""),
                                "vm_id": s.get("id", ""),
                                "image_name": img.get("name", img_id[:8]),
                                "image_created": img_created,
                                "suggestion": "Image older than 2 years — consider OS upgrade",
                            })
                    except Exception:
                        pass
                if img_status != "active":
                    tenant_opps.append({
                        "type": "deprecated_image",
                        "vm_name": s.get("name", ""),
                        "vm_id": s.get("id", ""),
                        "image_name": img.get("name", img_id[:8]),
                        "image_status": img_status,
                        "suggestion": f"Image status '{img_status}' — upgrade recommended",
                    })

        if tenant_opps:
            opportunities.append({
                "tenant_id": tid,
                "tenant_name": tname,
                "vm_count": len(servers),
                "opportunities": tenant_opps,
            })

    return {
        "result": {
            "opportunities": opportunities,
            "total_tenants_scanned": len(tenant_servers),
            "tenants_with_opportunities": len(opportunities),
            "estimated_revenue_delta_monthly": round(total_revenue_delta, 2),
            "currency": currency,
            "pricing_source": "metering_config",
        },
        "items_found": sum(len(o["opportunities"]) for o in opportunities),
        "items_actioned": 0,
    }


# ===== Engine: monthly_executive_snapshot =================================

@register_engine("monthly_executive_snapshot")
def _engine_executive_snapshot(params: dict, dry_run: bool, actor: str) -> dict:
    """Generate a monthly executive summary from DB and OpenStack."""
    from pf9_control import get_client

    top_n = params.get("risk_top_n", 5)
    include_deltas = params.get("include_deltas", True)

    # Load pricing from metering_config
    pricing = _load_metering_pricing()
    price_vcpu = pricing["price_per_vcpu_month"]
    price_gb_storage = pricing["price_per_gb_volume_month"]
    currency = pricing["cost_currency"]

    client = get_client()
    client.authenticate()
    headers = {"X-Auth-Token": client.token}

    report: Dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat()}

    # Totals from DB
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM projects")
            report["total_tenants"] = cur.fetchone()["cnt"]
            cur.execute("SELECT COUNT(*) AS cnt FROM servers")
            report["total_vms"] = cur.fetchone()["cnt"]
            cur.execute("SELECT COUNT(*) AS cnt FROM volumes")
            report["total_volumes"] = cur.fetchone()["cnt"]
            cur.execute("SELECT COALESCE(SUM(size_gb),0) AS total FROM volumes")
            report["total_storage_gb"] = cur.fetchone()["total"]
            cur.execute("SELECT COUNT(*) AS cnt FROM hypervisors")
            report["total_hypervisors"] = cur.fetchone()["cnt"]

            # Compliance: % of tenants that have at least one snapshot
            cur.execute("""
                SELECT COUNT(DISTINCT s.project_id) AS with_snap
                FROM snapshots s
                JOIN projects p ON s.project_id = p.id
            """)
            with_snap = cur.fetchone()["with_snap"]
            report["compliance_pct"] = round(with_snap / max(report["total_tenants"], 1) * 100, 1)

            # VMs by status
            cur.execute("SELECT status, COUNT(*) AS cnt FROM servers GROUP BY status ORDER BY cnt DESC")
            report["vms_by_status"] = {r["status"]: r["cnt"] for r in cur.fetchall()}

            # Month-over-month deltas
            if include_deltas:
                one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)
                cur.execute("SELECT COUNT(DISTINCT server_id) FROM servers_history WHERE recorded_at < %s", (one_month_ago,))
                prev_vms = cur.fetchone()[0]
                cur.execute("SELECT COUNT(DISTINCT project_id) FROM projects_history WHERE recorded_at < %s", (one_month_ago,))
                prev_tenants = cur.fetchone()[0]
                report["deltas"] = {
                    "vms": report["total_vms"] - prev_vms,
                    "tenants": report["total_tenants"] - prev_tenants,
                }

    # Capacity risk from hypervisors
    try:
        hv_resp = client.session.get(f"{client.nova_endpoint}/os-hypervisors/detail", headers=headers)
        hvs = hv_resp.json().get("hypervisors", []) if hv_resp.status_code == 200 else []
        at_risk = 0
        total_vcpus = 0
        total_ram = 0
        for hv in hvs:
            total_vcpus += hv.get("vcpus", 0)
            total_ram += hv.get("memory_mb", 0)
            mem_total = hv.get("memory_mb", 1)
            mem_used = hv.get("memory_mb_used", 0)
            if mem_total > 0 and (mem_used / mem_total) > 0.8:
                at_risk += 1
        report["capacity_risk"] = {
            "hypervisors_at_risk": at_risk,
            "total_hypervisors": len(hvs),
            "total_vcpus": total_vcpus,
            "total_ram_gb": round(total_ram / 1024, 1),
        }
    except Exception as e:
        report["capacity_risk"] = {"error": str(e)}

    # Revenue estimate
    report["revenue_estimate"] = {
        "monthly": round(total_vcpus * price_vcpu + report.get("total_storage_gb", 0) * price_gb_storage, 2),
        "price_per_vcpu": price_vcpu,
        "price_per_gb_storage": price_gb_storage,
        "currency": currency,
        "pricing_source": "metering_config",
    }

    # Top-N risk tenants
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT p.id, p.name,
                        COUNT(DISTINCT s.id) AS vm_count,
                        COUNT(DISTINCT CASE WHEN s.status = 'ERROR' THEN s.id END) AS error_vms,
                        COUNT(DISTINCT sn.id) AS snapshot_count
                    FROM projects p
                    LEFT JOIN servers s ON s.project_id = p.id
                    LEFT JOIN snapshots sn ON sn.project_id = p.id
                    GROUP BY p.id, p.name
                    ORDER BY COUNT(DISTINCT CASE WHEN s.status = 'ERROR' THEN s.id END) DESC,
                             COUNT(DISTINCT sn.id) ASC
                    LIMIT %s
                """, (top_n,))
                risk_tenants = []
                for r in cur.fetchall():
                    risk_score = r["error_vms"] * 10 + max(0, 5 - r["snapshot_count"])
                    risk_tenants.append({
                        "tenant_id": r["id"],
                        "tenant_name": r["name"],
                        "vm_count": r["vm_count"],
                        "error_vms": r["error_vms"],
                        "snapshot_count": r["snapshot_count"],
                        "risk_score": risk_score,
                    })
                report["top_risk_tenants"] = risk_tenants
    except Exception as e:
        report["top_risk_tenants_error"] = str(e)

    return {
        "result": report,
        "items_found": report.get("total_vms", 0),
        "items_actioned": 0,
    }


# ===== Engine: cost_leakage_report ========================================

@register_engine("cost_leakage_report")
def _engine_cost_leakage(params: dict, dry_run: bool, actor: str) -> dict:
    """Detect idle/wasted resources and estimate cost leakage."""
    from pf9_control import get_client

    idle_cpu_pct = params.get("idle_cpu_threshold_pct", 5)
    shutoff_days = params.get("shutoff_days_threshold", 30)
    detached_days = params.get("detached_volume_days", 7)

    # Load pricing from metering_config
    pricing = _load_metering_pricing()
    price_vcpu = pricing["price_per_vcpu_month"]
    price_vol = pricing["price_per_gb_volume_month"]
    price_fip = pricing["cost_per_floating_ip_month"]
    currency = pricing["cost_currency"]

    client = get_client()
    client.authenticate()
    headers = {"X-Auth-Token": client.token}
    project_names = _resolve_project_names(client, headers)

    now_utc = datetime.now(timezone.utc)
    shutoff_cutoff = now_utc - timedelta(days=shutoff_days)
    vol_cutoff = now_utc - timedelta(days=detached_days)

    leaks: Dict[str, list] = {"idle_vms": [], "shutoff_vms": [], "detached_volumes": [], "unused_fips": [], "oversized_vms": []}
    costs: Dict[str, float] = {"idle_vms": 0, "shutoff_vms": 0, "detached_volumes": 0, "unused_fips": 0, "oversized_vms": 0}

    # Servers
    srv_resp = client.session.get(
        f"{client.nova_endpoint}/servers/detail?all_tenants=true&limit=1000", headers=headers)
    all_servers = srv_resp.json().get("servers", []) if srv_resp.status_code == 200 else []

    # Flavor map
    flv_resp = client.session.get(f"{client.nova_endpoint}/flavors/detail", headers=headers)
    all_flavors = flv_resp.json().get("flavors", []) if flv_resp.status_code == 200 else []
    flavor_map = {f["id"]: f for f in all_flavors}

    # Load metrics cache for CPU utilisation
    cpu_metrics: Dict[str, float] = {}
    try:
        import json as _json
        cache_path = os.path.join(os.path.dirname(__file__), "..", "metrics_cache.json")
        if os.path.exists(cache_path):
            with open(cache_path) as f:
                cache = _json.load(f)
                for entry in cache.get("servers", []):
                    sid = entry.get("id", "")
                    cpu = entry.get("cpu_utilization_pct", -1)
                    if sid and cpu >= 0:
                        cpu_metrics[sid] = cpu
    except Exception:
        pass

    for s in all_servers:
        sid = s.get("id", "")
        vm_status = (s.get("status") or "").upper()
        tid = s.get("tenant_id", "")
        tname = project_names.get(tid, tid)
        flv_id = s.get("flavor", {}).get("id", "")
        flv = flavor_map.get(flv_id, {})
        vcpus = flv.get("vcpus", 0)
        ram_mb = flv.get("ram", 0)
        vm_cost = vcpus * price_vcpu

        # Shutoff VMs
        if vm_status == "SHUTOFF":
            updated = s.get("updated", s.get("created", ""))
            try:
                ts = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                if ts < shutoff_cutoff:
                    leaks["shutoff_vms"].append({
                        "vm_id": sid, "vm_name": s.get("name", ""),
                        "tenant_name": tname, "shutoff_since": updated,
                        "vcpus": vcpus, "monthly_cost": vm_cost,
                    })
                    costs["shutoff_vms"] += vm_cost
            except Exception:
                pass
            continue

        # Idle VMs (ACTIVE but low CPU)
        if vm_status == "ACTIVE" and sid in cpu_metrics:
            cpu = cpu_metrics[sid]
            if cpu < idle_cpu_pct:
                leaks["idle_vms"].append({
                    "vm_id": sid, "vm_name": s.get("name", ""),
                    "tenant_name": tname, "cpu_pct": round(cpu, 1),
                    "vcpus": vcpus, "monthly_cost": vm_cost,
                })
                costs["idle_vms"] += vm_cost

        # Oversized VMs (using <20% RAM)
        if vm_status == "ACTIVE" and ram_mb >= 4096:
            # Check if metrics show low memory usage (if available in cache)
            mem_entry = None
            try:
                cache_path2 = os.path.join(os.path.dirname(__file__), "..", "metrics_cache.json")
                if os.path.exists(cache_path2):
                    import json as _json2
                    with open(cache_path2) as f2:
                        cache2 = _json2.load(f2)
                        for entry in cache2.get("servers", []):
                            if entry.get("id") == sid:
                                mem_entry = entry.get("memory_utilization_pct", -1)
                                break
            except Exception:
                pass
            if mem_entry is not None and 0 <= mem_entry < 20:
                leaks["oversized_vms"].append({
                    "vm_id": sid, "vm_name": s.get("name", ""),
                    "tenant_name": tname, "ram_mb": ram_mb,
                    "mem_used_pct": round(mem_entry, 1),
                    "monthly_cost": vm_cost,
                })
                costs["oversized_vms"] += vm_cost * 0.5  # 50% could be saved

    # Detached volumes
    try:
        vol_resp = client.session.get(
            f"{client.cinder_endpoint}/volumes/detail?all_tenants=true", headers=headers)
        volumes = vol_resp.json().get("volumes", []) if vol_resp.status_code == 200 else []
        for v in volumes:
            if v.get("status") != "available" or v.get("attachments"):
                continue
            created = v.get("created_at", "")
            try:
                ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
                if ts > vol_cutoff:
                    continue
            except Exception:
                continue
            tid = v.get("os-vol-tenant-attr:tenant_id", "")
            size = v.get("size", 0)
            vol_cost = size * price_vol
            leaks["detached_volumes"].append({
                "volume_id": v["id"], "name": v.get("name", "") or v["id"][:8],
                "size_gb": size, "tenant_name": project_names.get(tid, tid),
                "created_at": created, "monthly_cost": vol_cost,
            })
            costs["detached_volumes"] += vol_cost
    except Exception:
        pass

    # Unused floating IPs
    try:
        fip_resp = client.session.get(
            f"{client.neutron_endpoint}/v2.0/floatingips", headers=headers)
        fips = fip_resp.json().get("floatingips", []) if fip_resp.status_code == 200 else []
        for f in fips:
            if f.get("port_id"):
                continue
            tid = f.get("project_id", "")
            leaks["unused_fips"].append({
                "fip_id": f["id"],
                "floating_ip": f.get("floating_ip_address", ""),
                "tenant_name": project_names.get(tid, tid),
                "monthly_cost": price_fip,
            })
            costs["unused_fips"] += price_fip
    except Exception:
        pass

    total_waste = round(sum(costs.values()), 2)
    return {
        "result": {
            "leaks": leaks,
            "costs_monthly": {k: round(v, 2) for k, v in costs.items()},
            "total_monthly_waste": total_waste,
            "total_items": sum(len(v) for v in leaks.values()),
            "currency": currency,
            "pricing_source": "metering_config",
        },
        "items_found": sum(len(v) for v in leaks.values()),
        "items_actioned": 0,
    }


# ===== Engine: password_reset_console =====================================

@register_engine("password_reset_console")
def _engine_password_console(params: dict, dry_run: bool, actor: str) -> dict:
    """Reset VM password and enable console access."""
    from pf9_control import get_client
    import secrets as _secrets

    server_id = params.get("server_id", "")
    if not server_id:
        return {"result": {"error": "server_id is required"}, "items_found": 0, "items_actioned": 0}

    new_password = params.get("new_password", "")
    enable_console = params.get("enable_console", True)
    console_expiry = params.get("console_expiry_minutes", 30)

    client = get_client()
    client.authenticate()
    headers = {"X-Auth-Token": client.token}

    # Get server detail
    srv_resp = client.session.get(f"{client.nova_endpoint}/servers/{server_id}", headers=headers)
    if srv_resp.status_code != 200:
        return {"result": {"error": f"Server not found: HTTP {srv_resp.status_code}"},
                "items_found": 0, "items_actioned": 0}
    server = srv_resp.json().get("server", {})
    vm_name = server.get("name", server_id[:8])

    # Check cloud-init support via image metadata
    cloud_init_supported = True
    cloud_init_note = ""
    img_id = server.get("image", {}).get("id", "")
    if img_id:
        try:
            img_resp = client.session.get(f"{client.glance_endpoint}/v2/images/{img_id}", headers=headers)
            if img_resp.status_code == 200:
                img_data = img_resp.json()
                os_type = (img_data.get("os_type", "") or img_data.get("os", "") or "").lower()
                if "windows" in os_type:
                    cloud_init_note = "Windows detected — cloudbase-init required"
                elif not os_type:
                    cloud_init_note = "OS type unknown — cloud-init support uncertain"
        except Exception:
            cloud_init_note = "Could not verify image metadata"
    else:
        cloud_init_note = "No image reference — booted from volume?"
        cloud_init_supported = True  # Assume supported

    result: Dict[str, Any] = {
        "server_id": server_id,
        "server_name": vm_name,
        "cloud_init_check": {"supported": cloud_init_supported, "note": cloud_init_note},
        "password_reset": {"attempted": False},
        "console_access": {"attempted": False},
        "audit": {
            "actor": actor,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "console_expiry_minutes": console_expiry,
        },
    }

    if dry_run:
        result["action"] = "dry_run — no changes made"
        return {"result": result, "items_found": 1, "items_actioned": 0}

    items_actioned = 0

    # Password reset via os-changePassword
    if not new_password:
        new_password = _secrets.token_urlsafe(16)
    try:
        pw_url = f"{client.nova_endpoint}/servers/{server_id}/action"
        pw_resp = client.session.post(pw_url, headers=headers,
                                      json={"changePassword": {"adminPass": new_password}})
        if pw_resp.status_code < 300:
            result["password_reset"] = {
                "attempted": True, "success": True,
                "password": new_password,
                "note": "Password injected via Nova changePassword API",
            }
            items_actioned += 1
        else:
            result["password_reset"] = {
                "attempted": True, "success": False,
                "error": f"HTTP {pw_resp.status_code}: {pw_resp.text[:200]}",
                "note": "changePassword may not be supported by this hypervisor/image",
            }
    except Exception as e:
        result["password_reset"] = {"attempted": True, "success": False, "error": str(e)}

    # Console access
    if enable_console:
        try:
            console_url = f"{client.nova_endpoint}/servers/{server_id}/action"
            # Try noVNC first
            cr = client.session.post(console_url, headers=headers,
                                     json={"os-getVNCConsole": {"type": "novnc"}})
            if cr.status_code == 200:
                console_data = cr.json().get("console", {})
                result["console_access"] = {
                    "attempted": True, "success": True,
                    "type": "noVNC",
                    "url": console_data.get("url", ""),
                    "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=console_expiry)).isoformat(),
                }
                items_actioned += 1
            else:
                # Fallback to SPICE
                cr2 = client.session.post(console_url, headers=headers,
                                          json={"os-getSPICEConsole": {"type": "spice-html5"}})
                if cr2.status_code == 200:
                    console_data = cr2.json().get("console", {})
                    result["console_access"] = {
                        "attempted": True, "success": True,
                        "type": "SPICE",
                        "url": console_data.get("url", ""),
                        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=console_expiry)).isoformat(),
                    }
                    items_actioned += 1
                else:
                    result["console_access"] = {
                        "attempted": True, "success": False,
                        "error": f"VNC: HTTP {cr.status_code}, SPICE: HTTP {cr2.status_code}",
                    }
        except Exception as e:
            result["console_access"] = {"attempted": True, "success": False, "error": str(e)}

    # Audit log to DB
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO activity_log (actor, action, resource_type, resource_id, details, timestamp)
                    VALUES (%s, %s, %s, %s, %s, now())
                """, (actor, "password_reset_console", "server", server_id,
                      json.dumps({"vm_name": vm_name, "console_expiry": console_expiry,
                                  "password_reset": result["password_reset"].get("success", False),
                                  "console_access": result["console_access"].get("success", False)})))
    except Exception as e:
        logger.warning(f"Audit log insert failed: {e}")

    return {"result": result, "items_found": 1, "items_actioned": items_actioned}


# ===== Engine: security_compliance_audit ==================================

@register_engine("security_compliance_audit")
def _engine_security_compliance(params: dict, dry_run: bool, actor: str) -> dict:
    """Comprehensive security & compliance audit."""
    from pf9_control import get_client

    stale_days = params.get("stale_user_days", 90)
    flag_wide_ports = params.get("flag_wide_port_ranges", True)
    check_encryption = params.get("check_volume_encryption", True)

    client = get_client()
    client.authenticate()
    headers = {"X-Auth-Token": client.token}
    project_names = _resolve_project_names(client, headers)

    findings: Dict[str, list] = {"sg_violations": [], "stale_users": [], "unencrypted_volumes": []}
    severity_counts = {"critical": 0, "warning": 0, "info": 0}

    # 1. Security group violations (extended)
    try:
        sg_resp = client.session.get(f"{client.neutron_endpoint}/v2.0/security-groups", headers=headers)
        sgs = sg_resp.json().get("security_groups", []) if sg_resp.status_code == 200 else []
        flag_ports = [22, 3389, 3306, 5432, 1433, 27017]
        for sg in sgs:
            for rule in sg.get("security_group_rules", []):
                if rule.get("direction") != "ingress":
                    continue
                remote = rule.get("remote_ip_prefix") or ""
                port_min = rule.get("port_range_min")
                port_max = rule.get("port_range_max")

                violation = None
                if remote in ("0.0.0.0/0", "::/0"):
                    # Wide open to internet
                    flagged = []
                    for fp in flag_ports:
                        if port_min is None and port_max is None:
                            flagged.append(fp)
                        elif port_min is not None and port_max is not None and port_min <= fp <= port_max:
                            flagged.append(fp)
                    if flagged:
                        violation = {
                            "type": "open_to_internet",
                            "severity": "critical",
                            "flagged_ports": flagged,
                        }
                        severity_counts["critical"] += 1

                # Wide port range check
                if flag_wide_ports and port_min is not None and port_max is not None:
                    if (port_max - port_min) >= 65535:
                        violation = violation or {}
                        violation.update({
                            "type": violation.get("type", "wide_port_range"),
                            "severity": "warning" if not violation.get("severity") else violation["severity"],
                            "wide_range": True,
                        })
                        if not violation.get("flagged_ports"):
                            severity_counts["warning"] += 1

                if violation:
                    pid = sg.get("project_id", "")
                    violation.update({
                        "sg_id": sg["id"],
                        "sg_name": sg.get("name", ""),
                        "project_name": project_names.get(pid, pid),
                        "rule_id": rule.get("id", ""),
                        "protocol": rule.get("protocol", "any"),
                        "port_range": f"{port_min or '*'}-{port_max or '*'}",
                        "remote_ip_prefix": remote or "any",
                    })
                    findings["sg_violations"].append(violation)
    except Exception as e:
        findings["sg_violations_error"] = str(e)

    # 2. Stale users
    try:
        stale_cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT u.id, u.name, u.domain_id, d.name AS domain_name,
                           u.enabled,
                           MAX(al.timestamp) AS last_activity
                    FROM users u
                    LEFT JOIN domains d ON u.domain_id = d.id
                    LEFT JOIN activity_log al ON al.actor = u.name
                    GROUP BY u.id, u.name, u.domain_id, d.name, u.enabled
                    HAVING MAX(al.timestamp) IS NULL OR MAX(al.timestamp) < %s
                    ORDER BY last_activity ASC NULLS FIRST
                """, (stale_cutoff,))
                for row in cur.fetchall():
                    sev = "warning" if row["enabled"] else "info"
                    severity_counts[sev] += 1
                    findings["stale_users"].append({
                        "user_id": row["id"],
                        "username": row["name"],
                        "domain": row["domain_name"] or row["domain_id"],
                        "enabled": row["enabled"],
                        "last_activity": row["last_activity"].isoformat() if row["last_activity"] else "never",
                        "severity": sev,
                    })
    except Exception as e:
        findings["stale_users_error"] = str(e)

    # 3. Unencrypted volumes
    if check_encryption:
        try:
            vol_resp = client.session.get(
                f"{client.cinder_endpoint}/volumes/detail?all_tenants=true", headers=headers)
            volumes = vol_resp.json().get("volumes", []) if vol_resp.status_code == 200 else []
            for v in volumes:
                encrypted = v.get("encrypted", False)
                if not encrypted:
                    tid = v.get("os-vol-tenant-attr:tenant_id", "")
                    severity_counts["info"] += 1
                    findings["unencrypted_volumes"].append({
                        "volume_id": v["id"],
                        "name": v.get("name", "") or v["id"][:8],
                        "size_gb": v.get("size", 0),
                        "status": v.get("status", ""),
                        "tenant_name": project_names.get(tid, tid),
                        "severity": "info",
                    })
        except Exception as e:
            findings["unencrypted_volumes_error"] = str(e)

    return {
        "result": {
            "findings": findings,
            "severity_counts": severity_counts,
            "total_findings": sum(len(v) for v in findings.values() if isinstance(v, list)),
        },
        "items_found": sum(len(v) for v in findings.values() if isinstance(v, list)),
        "items_actioned": 0,
    }


@register_engine("user_last_login")
def _engine_user_last_login(params: dict, dry_run: bool, actor: str) -> dict:
    """Report last login time for every user, flagging inactive ones."""
    days_threshold = params.get("days_inactive_threshold", 30)
    include_failed = params.get("include_failed_logins", False)

    users: list[dict] = []
    failed_logins: list[dict] = []
    now = datetime.now(timezone.utc)
    threshold_date = now - timedelta(days=days_threshold)
    inactive_count = 0
    never_logged_in = 0

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get all active users with roles
                cur.execute("""
                    SELECT ur.username, ur.role, ur.is_active,
                           (SELECT MAX(a.timestamp) FROM auth_audit_log a
                            WHERE a.username = ur.username AND a.action = 'login' AND a.success = true
                           ) AS last_login,
                           (SELECT a.ip_address FROM auth_audit_log a
                            WHERE a.username = ur.username AND a.action = 'login' AND a.success = true
                            ORDER BY a.timestamp DESC LIMIT 1
                           ) AS last_login_ip,
                           (SELECT COUNT(*) FROM auth_audit_log a
                            WHERE a.username = ur.username AND a.action = 'login' AND a.success = true
                           ) AS total_logins,
                           (SELECT MAX(s.last_activity) FROM user_sessions s
                            WHERE s.username = ur.username
                           ) AS last_session_activity,
                           (SELECT COUNT(*) FROM user_sessions s
                            WHERE s.username = ur.username AND s.is_active = true
                           ) AS active_sessions
                    FROM user_roles ur
                    WHERE ur.is_active = true
                    ORDER BY ur.username
                """)
                rows = cur.fetchall()

                for row in rows:
                    last_login = row["last_login"]
                    last_activity = row["last_session_activity"]
                    most_recent = max(filter(None, [last_login, last_activity]), default=None)

                    if most_recent is None:
                        status = "never_logged_in"
                        days_since = None
                        never_logged_in += 1
                        inactive_count += 1
                    else:
                        days_since = (now - most_recent).days
                        if days_since > days_threshold:
                            status = "inactive"
                            inactive_count += 1
                        else:
                            status = "active"

                    users.append({
                        "username": row["username"],
                        "role": row["role"],
                        "last_login": last_login.isoformat() if last_login else None,
                        "last_activity": last_activity.isoformat() if last_activity else None,
                        "last_login_ip": row["last_login_ip"],
                        "total_logins": row["total_logins"],
                        "active_sessions": row["active_sessions"],
                        "days_since_activity": days_since,
                        "status": status,
                    })

                # Optionally include recent failed logins
                if include_failed:
                    cur.execute("""
                        SELECT username, timestamp, ip_address, user_agent,
                               details
                        FROM auth_audit_log
                        WHERE action = 'failed_login'
                        ORDER BY timestamp DESC
                        LIMIT 50
                    """)
                    for row in cur.fetchall():
                        failed_logins.append({
                            "username": row["username"],
                            "timestamp": row["timestamp"].isoformat() if row["timestamp"] else None,
                            "ip_address": row["ip_address"],
                            "user_agent": row["user_agent"],
                            "details": row["details"],
                        })

    except Exception as e:
        return {
            "result": {"error": str(e)},
            "items_found": 0,
            "items_actioned": 0,
        }

    result = {
        "users": users,
        "summary": {
            "total_users": len(users),
            "active_users": len(users) - inactive_count,
            "inactive_users": inactive_count - never_logged_in,
            "never_logged_in": never_logged_in,
            "days_inactive_threshold": days_threshold,
        },
    }
    if include_failed and failed_logins:
        result["failed_logins"] = failed_logins

    return {
        "result": result,
        "items_found": len(users),
        "items_actioned": 0,
    }


# ---------------------------------------------------------------------------
#  Core execution logic
# ---------------------------------------------------------------------------
def _execute_runbook(execution_id: str, runbook_name: str, params: dict,
                     dry_run: bool, actor: str):
    """Run the runbook engine and update DB with results."""
    engine = RUNBOOK_ENGINES.get(runbook_name)
    if not engine:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE runbook_executions
                    SET status = 'failed', error_message = %s, completed_at = now()
                    WHERE execution_id = %s
                """, (f"No engine registered for runbook '{runbook_name}'", execution_id))
        return

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE runbook_executions SET status = 'executing', started_at = now()
                WHERE execution_id = %s
            """, (execution_id,))

    try:
        output = engine(params, dry_run, actor)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE runbook_executions
                    SET status = 'completed', result = %s,
                        items_found = %s, items_actioned = %s,
                        completed_at = now()
                    WHERE execution_id = %s
                """, (
                    json.dumps(output.get("result", {})),
                    output.get("items_found", 0),
                    output.get("items_actioned", 0),
                    execution_id,
                ))

        _notify(
            event_type="runbook_completed",
            summary=f"Runbook '{runbook_name}' completed — {output.get('items_found', 0)} found, {output.get('items_actioned', 0)} actioned",
            severity="info",
            resource_name=runbook_name,
            actor=actor,
        )

    except Exception as e:
        logger.error(f"Runbook execution {execution_id} failed: {e}\n{traceback.format_exc()}")
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE runbook_executions
                    SET status = 'failed', error_message = %s, completed_at = now()
                    WHERE execution_id = %s
                """, (str(e)[:2000], execution_id))
        _notify(
            event_type="runbook_failed",
            summary=f"Runbook '{runbook_name}' failed: {str(e)[:200]}",
            severity="critical",
            resource_name=runbook_name,
            actor=actor,
        )


# ---------------------------------------------------------------------------
#  API Endpoints
# ---------------------------------------------------------------------------

# ── List runbooks ────────────────────────────────────────────────
@router.get("")
async def list_runbooks(
    current_user=Depends(require_permission("runbooks", "read")),
):
    """List all runbook definitions."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT runbook_id, name, display_name, description, category,
                       risk_level, supports_dry_run, enabled,
                       parameters_schema, created_at, updated_at
                FROM runbooks ORDER BY category, display_name
            """)
            rows = cur.fetchall()
    return [dict(r) for r in rows]


# ── Get single runbook ───────────────────────────────────────────
@router.get("/{runbook_name}")
async def get_runbook(
    runbook_name: str,
    current_user=Depends(require_permission("runbooks", "read")),
):
    """Get a single runbook definition with its approval policies."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM runbooks WHERE name = %s", (runbook_name,))
            rb = cur.fetchone()
            if not rb:
                raise HTTPException(404, f"Runbook '{runbook_name}' not found")

            cur.execute("""
                SELECT * FROM runbook_approval_policies
                WHERE runbook_name = %s ORDER BY trigger_role
            """, (runbook_name,))
            policies = cur.fetchall()

    return {**dict(rb), "approval_policies": [dict(p) for p in policies]}


# ── Trigger runbook ──────────────────────────────────────────────
@router.post("/trigger")
async def trigger_runbook(
    body: TriggerRunbookRequest,
    request: Request,
    current_user=Depends(require_permission("runbooks", "write")),
):
    """Trigger a runbook execution. Depending on approval policy, it may
    execute immediately (auto_approve) or wait for approval."""
    user = current_user
    username = user.username if hasattr(user, "username") else str(user)
    role = user.role if hasattr(user, "role") else "operator"

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Validate runbook exists and is enabled
            cur.execute("SELECT * FROM runbooks WHERE name = %s AND enabled = true", (body.runbook_name,))
            rb = cur.fetchone()
            if not rb:
                raise HTTPException(404, f"Runbook '{body.runbook_name}' not found or disabled")

            # Check if engine exists
            if body.runbook_name not in RUNBOOK_ENGINES:
                raise HTTPException(501, f"No execution engine for runbook '{body.runbook_name}'")

            # Find matching approval policy
            cur.execute("""
                SELECT * FROM runbook_approval_policies
                WHERE runbook_name = %s AND trigger_role = %s AND enabled = true
            """, (body.runbook_name, role))
            policy = cur.fetchone()

            # Fallback: try 'operator' policy if exact role not found
            if not policy and role not in ("operator",):
                cur.execute("""
                    SELECT * FROM runbook_approval_policies
                    WHERE runbook_name = %s AND trigger_role = 'operator' AND enabled = true
                """, (body.runbook_name,))
                policy = cur.fetchone()

            if not policy:
                raise HTTPException(403, f"No approval policy allows role '{role}' to trigger '{body.runbook_name}'")

            approval_mode = policy["approval_mode"]

            # Rate-limit auto-approved executions
            if approval_mode == "auto_approve":
                cur.execute("""
                    SELECT COUNT(*) FROM runbook_executions
                    WHERE runbook_name = %s AND status IN ('completed', 'executing')
                      AND triggered_at >= now() - interval '24 hours'
                """, (body.runbook_name,))
                daily_count = cur.fetchone()["count"]
                if daily_count >= policy["max_auto_executions_per_day"]:
                    raise HTTPException(429, f"Daily auto-execution limit ({policy['max_auto_executions_per_day']}) reached for '{body.runbook_name}'")

            # Create execution record
            initial_status = "approved" if approval_mode == "auto_approve" else "pending_approval"
            cur.execute("""
                INSERT INTO runbook_executions
                    (runbook_name, status, dry_run, parameters, triggered_by)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING execution_id
            """, (body.runbook_name, initial_status, body.dry_run,
                  json.dumps(body.parameters), username))
            execution_id = cur.fetchone()["execution_id"]

            # If auto-approved, record approval and execute immediately
            if approval_mode == "auto_approve":
                cur.execute("""
                    INSERT INTO runbook_approvals (execution_id, approver, decision, comment)
                    VALUES (%s, %s, 'approved', 'Auto-approved by policy')
                """, (execution_id, "system"))

                cur.execute("""
                    UPDATE runbook_executions SET approved_by = 'system', approved_at = now()
                    WHERE execution_id = %s
                """, (execution_id,))

    # Execute if auto-approved (outside DB transaction)
    if approval_mode == "auto_approve":
        _execute_runbook(execution_id, body.runbook_name, body.parameters, body.dry_run, username)
    else:
        # Notify admins about pending approval
        _notify(
            event_type="runbook_approval_requested",
            summary=f"Runbook '{rb['display_name']}' triggered by {username} — awaiting {policy['approver_role']} approval",
            severity="warning",
            resource_name=body.runbook_name,
            actor=username,
        )

    # Fetch final state
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM runbook_executions WHERE execution_id = %s", (execution_id,))
            execution = cur.fetchone()

    return dict(execution)


# ── Approve / Reject execution ───────────────────────────────────
@router.post("/executions/{execution_id}/approve")
async def approve_reject_execution(
    execution_id: str,
    body: ApproveRejectRequest,
    request: Request,
    current_user=Depends(require_permission("runbooks", "admin")),
):
    """Approve or reject a pending runbook execution."""
    user = current_user
    username = user.username if hasattr(user, "username") else str(user)

    if body.decision not in ("approved", "rejected"):
        raise HTTPException(400, "Decision must be 'approved' or 'rejected'")

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM runbook_executions WHERE execution_id = %s
            """, (execution_id,))
            execution = cur.fetchone()
            if not execution:
                raise HTTPException(404, "Execution not found")
            if execution["status"] != "pending_approval":
                raise HTTPException(409, f"Execution is '{execution['status']}', not pending_approval")

            # Record approval
            cur.execute("""
                INSERT INTO runbook_approvals (execution_id, approver, decision, comment)
                VALUES (%s, %s, %s, %s)
            """, (execution_id, username, body.decision, body.comment))

            new_status = "approved" if body.decision == "approved" else "rejected"
            cur.execute("""
                UPDATE runbook_executions
                SET status = %s, approved_by = %s, approved_at = now()
                WHERE execution_id = %s
            """, (new_status, username, execution_id))

    if body.decision == "approved":
        _execute_runbook(
            execution_id, execution["runbook_name"],
            execution["parameters"], execution["dry_run"],
            execution["triggered_by"]
        )
        _notify(
            event_type="runbook_approval_granted",
            summary=f"Runbook '{execution['runbook_name']}' approved by {username} — executing now",
            severity="info",
            resource_name=execution["runbook_name"],
            actor=username,
        )
    else:
        _notify(
            event_type="runbook_approval_rejected",
            summary=f"Runbook '{execution['runbook_name']}' rejected by {username}: {body.comment or 'no comment'}",
            severity="warning",
            resource_name=execution["runbook_name"],
            actor=username,
        )

    # Fetch final state
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM runbook_executions WHERE execution_id = %s", (execution_id,))
            result = cur.fetchone()

    return dict(result)


# ── Cancel execution ─────────────────────────────────────────────
@router.post("/executions/{execution_id}/cancel")
async def cancel_execution(
    execution_id: str,
    current_user=Depends(require_permission("runbooks", "write")),
):
    """Cancel a pending execution."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                UPDATE runbook_executions
                SET status = 'cancelled', completed_at = now()
                WHERE execution_id = %s AND status = 'pending_approval'
                RETURNING *
            """, (execution_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Execution not found or not in pending_approval state")
    return dict(row)


# ── List executions (audit trail) ────────────────────────────────
@router.get("/executions/history")
async def list_executions(
    runbook_name: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("runbooks", "read")),
):
    """List runbook executions with optional filters."""
    clauses = []
    params_list: list = []

    if runbook_name:
        clauses.append("e.runbook_name = %s")
        params_list.append(runbook_name)
    if status_filter:
        clauses.append("e.status = %s")
        params_list.append(status_filter)

    where = "WHERE " + " AND ".join(clauses) if clauses else ""

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                SELECT e.*, r.display_name, r.category, r.risk_level
                FROM runbook_executions e
                LEFT JOIN runbooks r ON e.runbook_name = r.name
                {where}
                ORDER BY e.created_at DESC
                LIMIT %s OFFSET %s
            """, params_list + [limit, offset])
            rows = cur.fetchall()

            cur.execute(f"SELECT COUNT(*) FROM runbook_executions e {where}", params_list)
            total = cur.fetchone()["count"]

    return {"executions": [dict(r) for r in rows], "total": total}


# ── My executions (operator-facing) ──────────────────────────────
@router.get("/executions/mine")
async def my_executions(
    runbook_name: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("runbooks", "read")),
):
    """List executions triggered by the current user."""
    username = current_user.username if hasattr(current_user, "username") else str(current_user)

    clauses = ["e.triggered_by = %s"]
    params_list: list = [username]

    if runbook_name:
        clauses.append("e.runbook_name = %s")
        params_list.append(runbook_name)
    if status_filter:
        clauses.append("e.status = %s")
        params_list.append(status_filter)

    where = "WHERE " + " AND ".join(clauses)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                SELECT e.*, r.display_name, r.category, r.risk_level
                FROM runbook_executions e
                LEFT JOIN runbooks r ON e.runbook_name = r.name
                {where}
                ORDER BY e.created_at DESC
                LIMIT %s OFFSET %s
            """, params_list + [limit, offset])
            rows = cur.fetchall()

            cur.execute(f"SELECT COUNT(*) FROM runbook_executions e {where}", params_list)
            total = cur.fetchone()["count"]

    return {"executions": [dict(r) for r in rows], "total": total}


# ── Get single execution detail ──────────────────────────────────
@router.get("/executions/{execution_id}")
async def get_execution(
    execution_id: str,
    current_user=Depends(require_permission("runbooks", "read")),
):
    """Get full detail for a single execution including approval records."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT e.*, r.display_name, r.category, r.risk_level
                FROM runbook_executions e
                LEFT JOIN runbooks r ON e.runbook_name = r.name
                WHERE e.execution_id = %s
            """, (execution_id,))
            execution = cur.fetchone()
            if not execution:
                raise HTTPException(404, "Execution not found")

            cur.execute("""
                SELECT * FROM runbook_approvals
                WHERE execution_id = %s ORDER BY decided_at
            """, (execution_id,))
            approvals = cur.fetchall()

    return {**dict(execution), "approvals": [dict(a) for a in approvals]}


# ── Pending approvals ────────────────────────────────────────────
@router.get("/approvals/pending")
async def pending_approvals(
    current_user=Depends(require_permission("runbooks", "admin")),
):
    """List all executions waiting for approval."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT e.*, r.display_name, r.category, r.risk_level
                FROM runbook_executions e
                LEFT JOIN runbooks r ON e.runbook_name = r.name
                WHERE e.status = 'pending_approval'
                ORDER BY e.created_at ASC
            """)
            rows = cur.fetchall()
    return [dict(r) for r in rows]


# ── Approval policies CRUD ───────────────────────────────────────
@router.get("/policies/{runbook_name}")
async def get_policies(
    runbook_name: str,
    current_user=Depends(require_permission("runbooks", "admin")),
):
    """Get all approval policies for a runbook."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM runbook_approval_policies
                WHERE runbook_name = %s ORDER BY trigger_role
            """, (runbook_name,))
            rows = cur.fetchall()
    return [dict(r) for r in rows]


@router.put("/policies/{runbook_name}")
async def upsert_policy(
    runbook_name: str,
    body: ApprovalPolicyUpdate,
    current_user=Depends(require_permission("runbooks", "admin")),
):
    """Create or update an approval policy for a runbook."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO runbook_approval_policies
                    (runbook_name, trigger_role, approver_role, approval_mode,
                     escalation_timeout_minutes, max_auto_executions_per_day, enabled)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (runbook_name, trigger_role) DO UPDATE SET
                    approver_role = EXCLUDED.approver_role,
                    approval_mode = EXCLUDED.approval_mode,
                    escalation_timeout_minutes = EXCLUDED.escalation_timeout_minutes,
                    max_auto_executions_per_day = EXCLUDED.max_auto_executions_per_day,
                    enabled = EXCLUDED.enabled,
                    updated_at = now()
                RETURNING *
            """, (
                runbook_name, body.trigger_role, body.approver_role,
                body.approval_mode, body.escalation_timeout_minutes,
                body.max_auto_executions_per_day, body.enabled,
            ))
            row = cur.fetchone()
    return dict(row)


@router.delete("/policies/{runbook_name}/{trigger_role}")
async def delete_policy(
    runbook_name: str,
    trigger_role: str,
    current_user=Depends(require_permission("runbooks", "admin")),
):
    """Delete an approval policy."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM runbook_approval_policies
                WHERE runbook_name = %s AND trigger_role = %s
            """, (runbook_name, trigger_role))
            if cur.rowcount == 0:
                raise HTTPException(404, "Policy not found")
    return {"deleted": True}


# ── Execution stats ──────────────────────────────────────────────
@router.get("/stats/summary")
async def execution_stats(
    current_user=Depends(require_permission("runbooks", "read")),
):
    """Get summary statistics for runbook executions."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    runbook_name,
                    COUNT(*) as total_executions,
                    COUNT(*) FILTER (WHERE status = 'completed') as completed,
                    COUNT(*) FILTER (WHERE status = 'failed') as failed,
                    COUNT(*) FILTER (WHERE status = 'pending_approval') as pending,
                    COUNT(*) FILTER (WHERE status = 'rejected') as rejected,
                    SUM(items_found) as total_items_found,
                    SUM(items_actioned) as total_items_actioned,
                    MAX(created_at) as last_run
                FROM runbook_executions
                GROUP BY runbook_name
                ORDER BY runbook_name
            """)
            rows = cur.fetchall()
    return [dict(r) for r in rows]
