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


class RunbookVisibilityUpdate(BaseModel):
    dept_ids: List[int] = Field(default_factory=list)


# ---------------------------------------------------------------------------
#  Helper — billing gate (calls external billing integration if configured)
# ---------------------------------------------------------------------------
def _call_billing_gate(
    project_id: str, resource: str, units: float,
    cost_estimate: float, actor: str
) -> dict:
    """
    Call the configured billing_gate integration.
    Returns:
        {"skipped": True}                                — no active integration
        {"approved": bool, "charge_id": str|None, "reason": str}  — gate response
    Raises HTTPException(503) if the call itself fails.
    """
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM external_integrations
                    WHERE integration_type = 'billing_gate' AND enabled = true
                    LIMIT 1
                """)
                integration = cur.fetchone()
    except Exception as e:
        logger.warning(f"Could not query billing gate: {e}")
        return {"skipped": True, "reason": "billing gate query failed"}

    if not integration:
        return {"skipped": True, "reason": "no billing gate configured"}

    integration = dict(integration)

    # Decrypt credential using the same Fernet helper as integration_routes
    def _dec(ct: str) -> str:
        if not ct:
            return ""
        try:
            import base64, hashlib
            from cryptography.fernet import Fernet
            secret = os.environ.get("JWT_SECRET", "changeme-default-secret")
            key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
            return Fernet(key).decrypt(ct.encode()).decode()
        except Exception:
            return ct

    credential = _dec(integration.get("auth_credential") or "")
    headers = {"Content-Type": "application/json"}
    auth_type = integration.get("auth_type", "bearer")
    header_name = integration.get("auth_header_name", "Authorization")
    if credential:
        if auth_type == "bearer":
            headers[header_name] = f"Bearer {credential}"
        elif auth_type == "basic":
            import base64 as _b64
            headers[header_name] = "Basic " + _b64.b64encode(credential.encode()).decode()
        elif auth_type == "api_key":
            headers[header_name] = credential

    payload = dict(integration.get("request_template") or {})
    payload.update({
        "project_id": project_id,
        "resource": resource,
        "units": units,
        "cost_estimate": cost_estimate,
        "actor": actor,
    })

    try:
        import requests as _req
        resp = _req.post(
            integration["base_url"],
            json=payload,
            headers=headers,
            verify=bool(integration.get("verify_ssl", True)),
            timeout=int(integration.get("timeout_seconds", 10)),
        )
        resp.raise_for_status()
        data = resp.json()

        def _get_path(path: str):
            val = data
            for p in (path or "").split("."):
                val = val.get(p) if isinstance(val, dict) else None
            return val

        return {
            "approved": bool(_get_path(integration.get("response_approval_path", "approved"))),
            "charge_id": str(cid) if (cid := _get_path(integration.get("response_charge_id_path", "charge_id"))) else None,
            "reason": str(rsn) if (rsn := _get_path(integration.get("response_reason_path", "reason"))) else "",
        }
    except Exception as e:
        logger.error(f"Billing gate call failed: {e}")
        raise HTTPException(503, f"Billing gate integration error: {str(e)[:200]}")


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


# ===== Engine: snapshot_quota_forecast ====================================

@register_engine("snapshot_quota_forecast")
def _engine_snapshot_quota_forecast(params: dict, dry_run: bool, actor: str) -> dict:
    """
    Proactive daily runbook: forecast Cinder quota issues that would block
    upcoming snapshot runs.  For each project with snapshot-enabled volumes,
    compare the storage needed for one full snapshot cycle against the
    remaining Cinder gigabytes/snapshots quota and flag at-risk tenants.
    """
    from pf9_control import get_client

    include_pending = params.get("include_pending_policies", True)
    safety_margin_pct = params.get("safety_margin_pct", 10)

    client = get_client()
    client.authenticate()
    headers = {"X-Auth-Token": client.token}

    # --- Gather snapshot-enabled volumes from Cinder ---
    try:
        cinder_url = f"{client.cinder_endpoint}/volumes/detail?all_tenants=true"
        resp = client.session.get(cinder_url, headers=headers)
        resp.raise_for_status()
        all_volumes = resp.json().get("volumes", [])
    except Exception as e:
        return {
            "result": {"error": f"Failed to list volumes: {e}"},
            "items_found": 0,
            "items_actioned": 0,
        }

    # Filter to snapshot-enabled volumes
    snap_volumes = []
    for v in all_volumes:
        meta = v.get("metadata") or {}
        auto = str(meta.get("auto_snapshot", "")).lower()
        if auto in ("true", "yes", "1"):
            snap_volumes.append(v)

    # Group by project
    from collections import defaultdict
    by_project: dict[str, list] = defaultdict(list)
    for v in snap_volumes:
        pid = (
            v.get("os-vol-tenant-attr:tenant_id")
            or v.get("project_id")
            or "UNKNOWN"
        )
        by_project[pid].append(v)

    # --- Get project names ---
    project_names = {}
    try:
        ks_url = f"{client.keystone_endpoint}/projects"
        resp = client.session.get(ks_url, headers=headers)
        if resp.ok:
            for p in resp.json().get("projects", []):
                project_names[p["id"]] = p.get("name", p["id"])
    except Exception:
        pass

    # --- Check quota per project ---
    alerts: list[dict] = []
    ok_projects: list[dict] = []

    for project_id, vols in by_project.items():
        pname = project_names.get(project_id, project_id)
        total_vol_gb = sum(v.get("size", 0) for v in vols)
        vol_count = len(vols)

        # Fetch Cinder quota (usage=true to get in_use values)
        try:
            quota_url = (
                f"{client.cinder_endpoint.rstrip('/')}"
                f"/os-quota-sets/{project_id}?usage=true"
            )
            qr = client.session.get(quota_url, headers=headers)
            if qr.status_code != 200:
                alerts.append({
                    "project_id": project_id,
                    "project_name": pname,
                    "severity": "warning",
                    "issue": "quota_fetch_failed",
                    "detail": f"HTTP {qr.status_code} fetching Cinder quotas",
                    "volumes": vol_count,
                    "total_volume_gb": total_vol_gb,
                })
                continue
            qs = qr.json().get("quota_set", {})
        except Exception as e:
            alerts.append({
                "project_id": project_id,
                "project_name": pname,
                "severity": "warning",
                "issue": "quota_fetch_error",
                "detail": str(e),
                "volumes": vol_count,
                "total_volume_gb": total_vol_gb,
            })
            continue

        # Parse gigabytes
        gb_data = qs.get("gigabytes", {})
        if isinstance(gb_data, dict):
            gb_limit = gb_data.get("limit", -1)
            gb_used = gb_data.get("in_use", 0)
        else:
            gb_limit = int(gb_data) if gb_data else -1
            gb_used = 0

        # Parse snapshots count
        snap_data = qs.get("snapshots", {})
        if isinstance(snap_data, dict):
            snap_limit = snap_data.get("limit", -1)
            snap_used = snap_data.get("in_use", 0)
        else:
            snap_limit = int(snap_data) if snap_data else -1
            snap_used = 0

        # Calculate needed for one snapshot cycle
        gb_needed = total_vol_gb  # Each volume snapshot ≈ volume size
        snap_needed = vol_count

        # Apply safety margin
        margin_factor = 1 + (safety_margin_pct / 100)
        gb_needed_with_margin = gb_needed * margin_factor
        snap_needed_with_margin = snap_needed * margin_factor

        issues = []

        # Check gigabytes
        if gb_limit >= 0:
            gb_avail = gb_limit - gb_used
            gb_pct_used = round((gb_used / gb_limit) * 100, 1) if gb_limit > 0 else 0
            gb_pct_after = round(((gb_used + gb_needed) / gb_limit) * 100, 1) if gb_limit > 0 else 0

            if gb_used + gb_needed_with_margin > gb_limit:
                severity = "critical" if gb_used + gb_needed > gb_limit else "warning"
                issues.append({
                    "resource": "gigabytes",
                    "severity": severity,
                    "limit": gb_limit,
                    "used": gb_used,
                    "available": gb_avail,
                    "needed": gb_needed,
                    "needed_with_margin": round(gb_needed_with_margin, 1),
                    "pct_used": gb_pct_used,
                    "pct_after_snapshots": gb_pct_after,
                    "shortfall_gb": max(0, round((gb_used + gb_needed) - gb_limit, 1)),
                })

        # Check snapshot count
        if snap_limit >= 0:
            snap_avail = snap_limit - snap_used
            if snap_used + snap_needed_with_margin > snap_limit:
                severity = "critical" if snap_used + snap_needed > snap_limit else "warning"
                issues.append({
                    "resource": "snapshots",
                    "severity": severity,
                    "limit": snap_limit,
                    "used": snap_used,
                    "available": snap_avail,
                    "needed": snap_needed,
                    "needed_with_margin": round(snap_needed_with_margin),
                    "shortfall": max(0, (snap_used + snap_needed) - snap_limit),
                })

        if issues:
            worst_severity = "critical" if any(
                i["severity"] == "critical" for i in issues
            ) else "warning"
            alerts.append({
                "project_id": project_id,
                "project_name": pname,
                "severity": worst_severity,
                "issues": issues,
                "volumes": vol_count,
                "total_volume_gb": total_vol_gb,
                "gb_quota_limit": gb_limit,
                "gb_quota_used": gb_used,
                "snap_quota_limit": snap_limit,
                "snap_quota_used": snap_used,
            })
        else:
            ok_projects.append({
                "project_id": project_id,
                "project_name": pname,
                "volumes": vol_count,
                "total_volume_gb": total_vol_gb,
                "gb_quota_limit": gb_limit,
                "gb_quota_used": gb_used,
                "snap_quota_limit": snap_limit,
                "snap_quota_used": snap_used,
            })

    # Sort alerts by severity (critical first)
    alerts.sort(key=lambda a: (0 if a.get("severity") == "critical" else 1, a.get("project_name", "")))

    result = {
        "alerts": alerts,
        "ok_projects": ok_projects,
        "summary": {
            "total_projects_scanned": len(by_project),
            "projects_at_risk": len(alerts),
            "projects_ok": len(ok_projects),
            "critical_count": sum(1 for a in alerts if a.get("severity") == "critical"),
            "warning_count": sum(1 for a in alerts if a.get("severity") == "warning"),
            "total_snapshot_volumes": len(snap_volumes),
            "safety_margin_pct": safety_margin_pct,
        },
    }

    return {
        "result": result,
        "items_found": len(alerts),
        "items_actioned": 0,
    }


# ===== Engine: quota_adjustment ============================================

@register_engine("quota_adjustment")
def _engine_quota_adjustment(params: dict, dry_run: bool, actor: str) -> dict:
    """
    Set Nova / Neutron / Cinder quota for a project.
    Supports dry-run (returns before/after diff + cost estimate) and billing gate approval.
    """
    from pf9_control import get_client

    project_id = params.get("project_id", "")
    project_name = params.get("project_name", project_id)
    reason = params.get("reason", "")
    require_billing = params.get("require_billing_approval", True)

    if not project_id:
        raise HTTPException(400, "project_id is required")

    # Desired new quota values — only include keys explicitly passed and > 0
    nova_key_map    = {"new_vcpus": "cores", "new_ram_mb": "ram", "new_instances": "instances"}
    neutron_key_map = {"new_networks": "network"}
    cinder_key_map  = {"new_volumes": "volumes", "new_gigabytes": "gigabytes"}

    desired_nova    = {v: int(params[k]) for k, v in nova_key_map.items()    if params.get(k) is not None and int(params.get(k, 0) or 0) > 0}
    desired_neutron = {v: int(params[k]) for k, v in neutron_key_map.items() if params.get(k) is not None and int(params.get(k, 0) or 0) > 0}
    desired_cinder  = {v: int(params[k]) for k, v in cinder_key_map.items()  if params.get(k) is not None and int(params.get(k, 0) or 0) > 0}

    client = get_client()
    client.authenticate()
    headers = {"X-Auth-Token": client.token}

    # ----  1. Read current quotas ----
    before: dict = {"nova": {}, "neutron": {}, "cinder": {}}

    try:
        r = client.session.get(f"{client.nova_endpoint}/os-quota-sets/{project_id}/detail", headers=headers)
        if r.ok:
            qs = r.json().get("quota_set", {})
            for key in ("cores", "ram", "instances"):
                d = qs.get(key, {})
                before["nova"][key] = d.get("limit", -1) if isinstance(d, dict) else int(d or -1)
    except Exception as e:
        logger.warning(f"quota_adjustment: Nova read failed: {e}")

    try:
        r = client.session.get(f"{client.neutron_endpoint}/v2.0/quotas/{project_id}", headers=headers)
        if r.ok:
            qs = r.json().get("quota", {})
            before["neutron"]["network"] = qs.get("network", -1)
    except Exception as e:
        logger.warning(f"quota_adjustment: Neutron read failed: {e}")

    try:
        r = client.session.get(f"{client.cinder_endpoint}/os-quota-sets/{project_id}?usage=true", headers=headers)
        if r.ok:
            qs = r.json().get("quota_set", {})
            for key in ("volumes", "gigabytes"):
                d = qs.get(key, {})
                before["cinder"][key] = d.get("limit", -1) if isinstance(d, dict) else int(d or -1)
    except Exception as e:
        logger.warning(f"quota_adjustment: Cinder read failed: {e}")

    # ---- 2. Compute deltas (new − before) ----
    after = {"nova": desired_nova, "neutron": desired_neutron, "cinder": desired_cinder}

    deltas: dict = {}
    for svc, fields in after.items():
        for res, new_val in fields.items():
            old_val = before[svc].get(res, 0)
            deltas[f"{svc}.{res}"] = new_val - (old_val if old_val >= 0 else 0)

    any_increase = any(v > 0 for v in deltas.values())

    # ---- 3. Billing gate ----
    billing_result: dict = {"skipped": True, "reason": "no quota increase requested"}
    charge_id = None

    if any_increase and require_billing:
        pricing = _load_metering_pricing()
        cost_est = round(
            max(0, deltas.get("nova.cores", 0)) * pricing.get("price_per_vcpu_month", 15)
            + max(0, deltas.get("nova.ram", 0) / 1024) * pricing.get("price_per_gb_ram_month", 5)
            + max(0, deltas.get("cinder.gigabytes", 0)) * pricing.get("price_per_gb_volume_month", 2),
            2,
        )
        billing_result = _call_billing_gate(
            project_id=project_id,
            resource="quota_increase",
            units=sum(max(0, v) for v in deltas.values()),
            cost_estimate=cost_est,
            actor=actor,
        )
        if not billing_result.get("skipped") and not billing_result.get("approved"):
            return {
                "result": {
                    "billing_rejected": True,
                    "reason": billing_result.get("reason", "rejected by billing gate"),
                    "before": before,
                    "after": after,
                    "deltas": deltas,
                    "cost_estimate": cost_est,
                    "cost_currency": pricing.get("cost_currency", "USD"),
                },
                "items_found": len(deltas),
                "items_actioned": 0,
            }
        charge_id = billing_result.get("charge_id")

    # ---- 4. Dry-run: return diff + simulation ----
    if dry_run:
        pricing = _load_metering_pricing()
        cost_est = round(
            max(0, deltas.get("nova.cores", 0)) * pricing.get("price_per_vcpu_month", 15)
            + max(0, deltas.get("nova.ram", 0) / 1024) * pricing.get("price_per_gb_ram_month", 5)
            + max(0, deltas.get("cinder.gigabytes", 0)) * pricing.get("price_per_gb_volume_month", 2),
            2,
        )
        return {
            "result": {
                "dry_run": True,
                "before": before,
                "after": after,
                "deltas": deltas,
                "billing_gate_simulation": billing_result,
                "cost_estimate": cost_est,
                "cost_currency": pricing.get("cost_currency", "USD"),
                "reason": reason,
            },
            "items_found": len([k for k, v in deltas.items() if v != 0]),
            "items_actioned": 0,
        }

    # ---- 5. Apply quotas ----
    applied: dict = {}
    errors: list = []

    if desired_nova:
        try:
            r = client.session.put(
                f"{client.nova_endpoint}/os-quota-sets/{project_id}",
                json={"quota_set": desired_nova}, headers=headers)
            r.raise_for_status()
            applied["nova"] = desired_nova
        except Exception as e:
            errors.append(f"Nova quota update failed: {e}")

    if desired_neutron:
        try:
            r = client.session.put(
                f"{client.neutron_endpoint}/v2.0/quotas/{project_id}",
                json={"quota": desired_neutron}, headers=headers)
            r.raise_for_status()
            applied["neutron"] = desired_neutron
        except Exception as e:
            errors.append(f"Neutron quota update failed: {e}")

    if desired_cinder:
        try:
            r = client.session.put(
                f"{client.cinder_endpoint}/os-quota-sets/{project_id}",
                json={"quota_set": desired_cinder}, headers=headers)
            r.raise_for_status()
            applied["cinder"] = desired_cinder
        except Exception as e:
            errors.append(f"Cinder quota update failed: {e}")

    items_actioned = sum(len(v) for v in applied.values())

    # ---- 6. Audit log ----
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO activity_log (actor, action, resource_type, resource_id, details, timestamp)
                    VALUES (%s, %s, %s, %s, %s, now())
                """, (actor, "quota_adjustment", "project", project_id,
                      json.dumps({"before": before, "after": after, "applied": applied,
                                  "charge_id": charge_id, "reason": reason,
                                  "project_name": project_name, "errors": errors})))
    except Exception as e:
        logger.warning(f"Audit log insert failed: {e}")

    return {
        "result": {
            "before": before,
            "after": after,
            "applied": applied,
            "deltas": deltas,
            "billing_gate": billing_result,
            "charge_id": charge_id,
            "reason": reason,
            "project_name": project_name,
            "errors": errors,
        },
        "items_found": len(deltas),
        "items_actioned": items_actioned,
    }


# ===== Engine: org_usage_report ============================================

@register_engine("org_usage_report")
def _engine_org_usage_report(params: dict, dry_run: bool, actor: str) -> dict:
    """
    Complete read-only usage + cost report for a single org/project.
    Returns structured JSON and a pre-rendered HTML body (email-ready).
    """
    from pf9_control import get_client

    project_id = params.get("project_id", "")
    include_cost = params.get("include_cost_estimate", True)
    include_snapshots = params.get("include_snapshot_details", True)
    period_days = int(params.get("period_days", 30) or 30)

    if not project_id:
        raise HTTPException(400, "project_id is required")

    client = get_client()
    client.authenticate()
    headers = {"X-Auth-Token": client.token}

    # Resolve project name
    project_name = project_id
    try:
        r = client.session.get(f"{client.keystone_endpoint}/projects/{project_id}", headers=headers)
        if r.ok:
            project_name = r.json().get("project", {}).get("name", project_id)
    except Exception:
        pass

    usage: dict = {}
    quota: dict = {}

    # ---- Nova (compute) quota ----
    try:
        r = client.session.get(f"{client.nova_endpoint}/os-quota-sets/{project_id}/detail", headers=headers)
        if r.ok:
            qs = r.json().get("quota_set", {})
            for key in ("cores", "ram", "instances"):
                d = qs.get(key, {})
                if isinstance(d, dict):
                    quota[f"nova.{key}"] = {"limit": d.get("limit", -1), "in_use": d.get("in_use", 0)}
                else:
                    quota[f"nova.{key}"] = {"limit": int(d or -1), "in_use": 0}
    except Exception as e:
        logger.warning(f"org_usage_report: Nova quota failed: {e}")

    # Server list
    servers: list = []
    try:
        r = client.session.get(
            f"{client.nova_endpoint}/servers/detail?all_tenants=true&project_id={project_id}",
            headers=headers)
        if r.ok:
            servers = r.json().get("servers", [])
    except Exception as e:
        logger.warning(f"org_usage_report: server list failed: {e}")

    usage["servers_total"]   = len(servers)
    usage["servers_active"]  = sum(1 for s in servers if s.get("status") == "ACTIVE")
    usage["servers_stopped"] = sum(1 for s in servers if s.get("status") in ("SHUTOFF", "STOPPED"))
    usage["vcpus_in_use"]    = sum(s.get("flavor", {}).get("vcpus", 0) for s in servers)
    usage["ram_mb_in_use"]   = sum(s.get("flavor", {}).get("ram", 0) for s in servers)

    # ---- Neutron (network) quota ----
    try:
        r = client.session.get(f"{client.neutron_endpoint}/v2.0/quotas/{project_id}", headers=headers)
        if r.ok:
            qs = r.json().get("quota", {})
            for key in ("network", "floatingip", "router", "port", "security_group"):
                quota[f"neutron.{key}"] = {"limit": qs.get(key, -1), "in_use": None}
    except Exception as e:
        logger.warning(f"org_usage_report: Neutron quota failed: {e}")

    # Floating IPs
    floating_ips: list = []
    try:
        r = client.session.get(
            f"{client.neutron_endpoint}/v2.0/floatingips?project_id={project_id}",
            headers=headers)
        if r.ok:
            floating_ips = r.json().get("floatingips", [])
            if "neutron.floatingip" in quota:
                quota["neutron.floatingip"]["in_use"] = len(floating_ips)
    except Exception as e:
        logger.warning(f"org_usage_report: floating IP list failed: {e}")
    usage["floating_ips"] = len(floating_ips)

    # ---- Cinder (block storage) quota ----
    try:
        r = client.session.get(
            f"{client.cinder_endpoint}/os-quota-sets/{project_id}?usage=true",
            headers=headers)
        if r.ok:
            qs = r.json().get("quota_set", {})
            for key in ("volumes", "gigabytes", "snapshots"):
                d = qs.get(key, {})
                if isinstance(d, dict):
                    quota[f"cinder.{key}"] = {"limit": d.get("limit", -1), "in_use": d.get("in_use", 0)}
                else:
                    quota[f"cinder.{key}"] = {"limit": int(d or -1), "in_use": 0}
    except Exception as e:
        logger.warning(f"org_usage_report: Cinder quota failed: {e}")

    # Volumes list
    volumes: list = []
    try:
        r = client.session.get(
            f"{client.cinder_endpoint}/volumes/detail?all_tenants=true&project_id={project_id}",
            headers=headers)
        if r.ok:
            volumes = r.json().get("volumes", [])
    except Exception as e:
        logger.warning(f"org_usage_report: volume list failed: {e}")
    usage["volumes"]   = len(volumes)
    usage["volume_gb"] = sum(v.get("size", 0) for v in volumes)

    # Snapshots
    snapshots_list: list = []
    if include_snapshots:
        try:
            r = client.session.get(
                f"{client.cinder_endpoint}/snapshots/detail?all_tenants=true&project_id={project_id}",
                headers=headers)
            if r.ok:
                snapshots_list = r.json().get("snapshots", [])
        except Exception as e:
            logger.warning(f"org_usage_report: snapshot list failed: {e}")
    usage["snapshots"]    = len(snapshots_list)
    usage["snapshot_gb"]  = sum(s.get("size", 0) for s in snapshots_list)

    # ---- Utilisation % ----
    utilisation: dict = {}
    for metric, q in quota.items():
        lim    = q.get("limit", -1)
        in_use = q.get("in_use") or 0
        utilisation[metric] = round(in_use / lim * 100, 1) if lim and lim > 0 else None

    # ---- Cost estimate ----
    cost_summary: dict = {}
    if include_cost:
        pricing    = _load_metering_pricing()
        currency   = pricing.get("cost_currency", "USD")
        factor     = period_days / 30.0
        cost_compute  = round(
            usage.get("vcpus_in_use", 0)  * pricing.get("price_per_vcpu_month", 15) * factor
            + (usage.get("ram_mb_in_use", 0) / 1024) * pricing.get("price_per_gb_ram_month", 5) * factor,
            2,
        )
        cost_storage  = round(usage.get("volume_gb", 0)    * pricing.get("price_per_gb_volume_month", 2)   * factor, 2)
        cost_snaps    = round(usage.get("snapshot_gb", 0)  * pricing.get("cost_per_snapshot_gb_month", 1.5) * factor, 2)
        cost_fips     = round(usage.get("floating_ips", 0) * pricing.get("cost_per_floating_ip_month", 5)   * factor, 2)
        cost_summary  = {
            "compute":       cost_compute,
            "block_storage": cost_storage,
            "snapshots":     cost_snaps,
            "floating_ips":  cost_fips,
            "total":         round(cost_compute + cost_storage + cost_snaps + cost_fips, 2),
            "currency":      currency,
            "period_days":   period_days,
        }

    # ---- HTML Report ----
    def _util_bar(pct):
        if pct is None:
            return "unlimited"
        color = "#e74c3c" if pct >= 90 else "#f39c12" if pct >= 75 else "#27ae60"
        return (
            f'<span style="font-weight:bold;color:{color}">{pct}%</span>'
            f'<div style="background:#eee;border-radius:3px;height:8px;width:100px;display:inline-block;margin-left:6px">'
            f'<div style="background:{color};width:{min(pct, 100)}%;height:8px;border-radius:3px"></div></div>'
        )

    rows_quota = ""
    for metric, q in quota.items():
        lim      = q.get("limit", -1)
        in_use   = q.get("in_use") or 0
        lim_disp = "unlimited" if lim == -1 else str(lim)
        pct      = utilisation.get(metric)
        rows_quota += (
            f"<tr>"
            f"<td style='padding:6px 10px'>{metric}</td>"
            f"<td style='padding:6px 10px;text-align:right'>{in_use}</td>"
            f"<td style='padding:6px 10px;text-align:right'>{lim_disp}</td>"
            f"<td style='padding:6px 10px'>{_util_bar(pct)}</td>"
            f"</tr>"
        )

    cost_rows = ""
    if cost_summary:
        for cat, val in cost_summary.items():
            if cat in ("currency", "period_days", "total"):
                continue
            cost_rows += (
                f"<tr><td style='padding:6px 10px'>{cat.replace('_', ' ').title()}</td>"
                f"<td style='padding:6px 10px;text-align:right'>"
                f"{cost_summary['currency']} {val:.2f}</td></tr>"
            )
        cost_rows += (
            f"<tr style='font-weight:bold;border-top:2px solid #333'>"
            f"<td style='padding:6px 10px'>Total ({period_days}d)</td>"
            f"<td style='padding:6px 10px;text-align:right'>"
            f"{cost_summary['currency']} {cost_summary['total']:.2f}</td></tr>"
        )

    cost_section = ""
    if cost_rows:
        cost_section = (
            "<h3>Cost Estimate</h3>"
            "<table style='border-collapse:collapse;width:50%;font-size:13px'>"
            "<thead><tr style='background:#2ecc71;color:#fff'>"
            "<th style='padding:8px 10px;text-align:left'>Category</th>"
            "<th style='padding:8px 10px;text-align:right'>Estimated Cost</th>"
            "</tr></thead>"
            f"<tbody>{cost_rows}</tbody></table>"
        )

    html_body = (
        "<div style='font-family:Arial,sans-serif;max-width:720px'>"
        f"<h2 style='border-bottom:2px solid #3498db;padding-bottom:8px'>Usage Report: {project_name}</h2>"
        f"<p>Report period: <b>{period_days} days</b> &nbsp;|&nbsp; Generated by: <b>{actor}</b></p>"
        "<h3>Resource Summary</h3><ul>"
        f"<li>Servers: <b>{usage.get('servers_total', 0)}</b>"
        f" ({usage.get('servers_active', 0)} active, {usage.get('servers_stopped', 0)} stopped)</li>"
        f"<li>vCPUs in use: <b>{usage.get('vcpus_in_use', 0)}</b></li>"
        f"<li>RAM in use: <b>{usage.get('ram_mb_in_use', 0)} MB"
        f" ({usage.get('ram_mb_in_use', 0) // 1024} GB)</b></li>"
        f"<li>Volumes: <b>{usage.get('volumes', 0)}</b> ({usage.get('volume_gb', 0)} GB)</li>"
        f"<li>Snapshots: <b>{usage.get('snapshots', 0)}</b> ({usage.get('snapshot_gb', 0)} GB)</li>"
        f"<li>Floating IPs: <b>{usage.get('floating_ips', 0)}</b></li>"
        "</ul>"
        "<h3>Quota Utilisation</h3>"
        "<table style='border-collapse:collapse;width:100%;font-size:13px'>"
        "<thead><tr style='background:#3498db;color:#fff'>"
        "<th style='padding:8px 10px;text-align:left'>Resource</th>"
        "<th style='padding:8px 10px;text-align:right'>In Use</th>"
        "<th style='padding:8px 10px;text-align:right'>Limit</th>"
        "<th style='padding:8px 10px;text-align:left'>Utilisation</th>"
        "</tr></thead>"
        f"<tbody>{rows_quota}</tbody></table>"
        f"{cost_section}"
        "</div>"
    )

    result = {
        "project_id":       project_id,
        "project_name":     project_name,
        "period_days":      period_days,
        "usage":            usage,
        "quota":            quota,
        "utilisation_pct":  utilisation,
        "html_body":        html_body,
    }
    if cost_summary:
        result["cost_estimate"] = cost_summary

    return {
        "result": result,
        "items_found": len(quota),
        "items_actioned": 0,
    }


# ===== Engine: vm_rightsizing =============================================

@register_engine("vm_rightsizing")
def _engine_vm_rightsizing(params: dict, dry_run: bool, actor: str) -> dict:
    """
    Analyse VM CPU / RAM usage from metering data and suggest (or apply)
    downsizes to a smaller, cheaper flavor.

    Parameters
    ----------
    target_project      : project ID to scope the analysis (blank = all)
    server_ids          : list of VM IDs to analyse (blank = all in project)
    analysis_days       : how many days of metering history to consider (default 14)
    cpu_idle_pct        : max avg CPU % to be a candidate (default 15)
    ram_idle_pct        : max avg RAM % to be a candidate (default 30)
    min_savings_per_month : minimum USD savings to include in candidate list (default 5)
    require_snapshot_first : take a snapshot before resizing (default True)
    """
    import time
    from pf9_control import get_client

    target_project = params.get("target_project", "")
    server_ids_filter = params.get("server_ids", [])
    analysis_days = int(params.get("analysis_days", 14))
    cpu_idle_pct = float(params.get("cpu_idle_pct", 15))
    ram_idle_pct = float(params.get("ram_idle_pct", 30))
    min_savings = float(params.get("min_savings_per_month", 5))
    require_snapshot = params.get("require_snapshot_first", True)

    pricing = _load_metering_pricing()
    price_vcpu = pricing.get("price_per_vcpu_month", 15.0)
    price_gb_ram = pricing.get("price_per_gb_ram_month", 5.0)
    currency = pricing.get("cost_currency", "USD")

    # ── 1. Pull average usage from metering_resources ──────────────────────
    usage_map: Dict[str, dict] = {}
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        vm_id,
                        vm_name,
                        project_name,
                        vcpus_allocated,
                        ram_allocated_mb,
                        AVG(cpu_usage_percent)::numeric(6,2)  AS avg_cpu_pct,
                        AVG(ram_usage_percent)::numeric(6,2)  AS avg_ram_pct,
                        AVG(ram_usage_mb)::numeric(12,2)      AS avg_ram_mb,
                        MAX(cpu_usage_percent)::numeric(6,2)  AS peak_cpu_pct,
                        MAX(ram_usage_percent)::numeric(6,2)  AS peak_ram_pct,
                        COUNT(*)                               AS data_points
                    FROM metering_resources
                    WHERE collected_at > now() - interval '%s days'
                    GROUP BY vm_id, vm_name, project_name, vcpus_allocated, ram_allocated_mb
                    HAVING COUNT(*) >= 3
                """, (analysis_days,))
                for row in cur.fetchall():
                    usage_map[row["vm_id"]] = dict(row)
    except Exception as e:
        logger.error(f"vm_rightsizing: metering query failed: {e}")
        raise HTTPException(500, f"Metering data query failed: {e}")

    # ── 2. Fetch Nova flavor catalog ────────────────────────────────────────
    client = get_client()
    client.authenticate()
    headers = {"X-Auth-Token": client.token}

    try:
        fl_resp = client.session.get(
            f"{client.nova_endpoint}/flavors/detail?is_public=None",
            headers=headers,
        )
        fl_resp.raise_for_status()
        nova_flavors = fl_resp.json().get("flavors", [])
    except Exception as e:
        logger.error(f"vm_rightsizing: flavor fetch failed: {e}")
        raise HTTPException(500, f"Could not fetch flavor list: {e}")

    # Build flavor lookup: id→{vcpus, ram_mb, disk_gb, name}
    flavor_by_id: Dict[str, dict] = {
        f["id"]: {
            "id": f["id"],
            "name": f.get("name", ""),
            "vcpus": f.get("vcpus", 0),
            "ram_mb": f.get("ram", 0),
            "disk_gb": f.get("disk", 0),
        }
        for f in nova_flavors
    }

    # Augment flavor cost from metering_pricing by matching name
    flavor_cost: Dict[str, float] = {}
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT item_name, vcpus, ram_gb, cost_per_month
                    FROM metering_pricing
                    WHERE category = 'flavor' AND vcpus > 0 AND cost_per_month > 0
                """)
                for row in cur.fetchall():
                    flavor_cost[row["item_name"]] = float(row["cost_per_month"])
    except Exception as e:
        logger.warning(f"vm_rightsizing: could not load flavor pricing: {e}")

    def _flavor_cost(flv: dict) -> float:
        """Estimate monthly cost for a flavor, using metering_pricing or formula."""
        cost = flavor_cost.get(flv["name"])
        if cost:
            return cost
        vcpus = flv["vcpus"]
        ram_gb = flv["ram_mb"] / 1024.0
        return round(vcpus * price_vcpu + ram_gb * price_gb_ram, 2)

    # ── 3. Fetch VMs from Nova ──────────────────────────────────────────────
    url = f"{client.nova_endpoint}/servers/detail?all_tenants=true&limit=1000"
    if target_project:
        url += f"&project_id={target_project}"
    try:
        srv_resp = client.session.get(url, headers=headers)
        srv_resp.raise_for_status()
        all_servers = srv_resp.json().get("servers", [])
    except Exception as e:
        raise HTTPException(500, f"Could not fetch server list: {e}")

    # ── 4. Find candidates ─────────────────────────────────────────────────
    candidates = []
    skipped = []

    for srv in all_servers:
        sid = srv["id"]

        # Filter by explicit server_ids list if provided
        if server_ids_filter and sid not in server_ids_filter:
            continue

        srv_status = srv.get("status", "")
        if srv_status.upper() not in ("ACTIVE", "SHUTOFF"):
            skipped.append({"vm_id": sid, "vm_name": srv.get("name", ""), "reason": f"status={srv_status}"})
            continue

        usage = usage_map.get(sid)
        if not usage:
            skipped.append({"vm_id": sid, "vm_name": srv.get("name", ""), "reason": "no metering data"})
            continue

        avg_cpu = float(usage["avg_cpu_pct"] or 0)
        avg_ram_pct = float(usage["avg_ram_pct"] or 0)
        if avg_cpu >= cpu_idle_pct or avg_ram_pct >= ram_idle_pct:
            continue  # Not over-provisioned

        # Current flavor
        current_flavor_id = srv.get("flavor", {}).get("id", "")
        current_flavor = flavor_by_id.get(current_flavor_id)
        if not current_flavor:
            skipped.append({"vm_id": sid, "vm_name": srv.get("name", ""), "reason": "flavor not found"})
            continue

        current_cost = _flavor_cost(current_flavor)

        # Required resources (peak + headroom)
        peak_cpu_pct = float(usage["peak_cpu_pct"] or avg_cpu)
        peak_ram_pct = float(usage["peak_ram_pct"] or usage["avg_ram_pct"] or 0)
        current_vcpus = current_flavor["vcpus"]
        current_ram_mb = current_flavor["ram_mb"]

        # Need enough for peak usage × safety margin
        # peak_ram_pct is actual % used; ram_usage_mb stores allocated (not actual used)
        peak_ram_mb_actual = (peak_ram_pct / 100.0) * current_ram_mb
        min_vcpus = max(1, int(round((peak_cpu_pct / 100.0) * current_vcpus * 1.25 + 0.5)))
        min_ram_mb = int(peak_ram_mb_actual * 1.5)

        # Must actually be smaller than current
        if min_vcpus >= current_vcpus and min_ram_mb >= current_ram_mb:
            continue  # Headroom calc says keep current size

        # Find cheapest smaller-or-equal flavor that covers minimum requirements
        best_flavor = None
        best_cost = current_cost
        for flv in flavor_by_id.values():
            if flv["vcpus"] < min_vcpus:
                continue
            if flv["ram_mb"] < min_ram_mb:
                continue
            if flv["vcpus"] > current_vcpus and flv["ram_mb"] > current_ram_mb:
                continue  # Don't upsize both dimensions
            if flv["id"] == current_flavor_id:
                continue
            flv_cost = _flavor_cost(flv)
            if flv_cost < best_cost:
                best_cost = flv_cost
                best_flavor = flv

        if not best_flavor:
            continue

        savings = round(current_cost - best_cost, 2)
        if savings < min_savings:
            continue

        tenant_id = srv.get("tenant_id", "")
        candidates.append({
            "vm_id": sid,
            "vm_name": srv.get("name", ""),
            "project_id": tenant_id,
            "project_name": usage["project_name"] or tenant_id,
            "status": srv_status,
            "current_flavor": {
                "id": current_flavor_id,
                "name": current_flavor["name"],
                "vcpus": current_flavor["vcpus"],
                "ram_mb": current_flavor["ram_mb"],
                "cost_per_month": current_cost,
            },
            "suggested_flavor": {
                "id": best_flavor["id"],
                "name": best_flavor["name"],
                "vcpus": best_flavor["vcpus"],
                "ram_mb": best_flavor["ram_mb"],
                "cost_per_month": best_cost,
            },
            "savings_per_month": savings,
            "avg_cpu_pct": avg_cpu,
            "avg_ram_pct": avg_ram_pct,
            "peak_cpu_pct": peak_cpu_pct,
            "peak_ram_mb": round(peak_ram_mb_actual, 1),
            "data_points": int(usage["data_points"]),
            "analysis_days": analysis_days,
        })

    total_savings = round(sum(c["savings_per_month"] for c in candidates), 2)

    if dry_run or not candidates:
        return {
            "result": {
                "candidates": candidates,
                "skipped": skipped,
                "total_candidates": len(candidates),
                "total_savings_per_month": total_savings,
                "currency": currency,
                "analysis_days": analysis_days,
                "cpu_idle_threshold_pct": cpu_idle_pct,
                "ram_idle_threshold_pct": ram_idle_pct,
                "mode": "dry_run" if dry_run else "scan",
                "resized": [],
                "errors": [],
            },
            "items_found": len(candidates),
            "items_actioned": 0,
        }

    # ── 5. Actual resize ───────────────────────────────────────────────────
    resized = []
    errors = []
    items_actioned = 0

    def _poll_status(sid: str, target_status: str, timeout: int = 300) -> bool:
        """Poll Nova until VM reaches target_status. Returns True on success."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = client.session.get(f"{client.nova_endpoint}/servers/{sid}", headers=headers)
            if r.status_code == 200:
                st = r.json().get("server", {}).get("status", "")
                if st.upper() == target_status.upper():
                    return True
                if st.upper() in ("ERROR",):
                    return False
            time.sleep(10)
        return False

    for c in candidates:
        sid = c["vm_id"]
        new_flavor_id = c["suggested_flavor"]["id"]
        was_active = c["status"].upper() == "ACTIVE"
        snap_result = None

        try:
            # 5a. Snapshot first if required
            if require_snapshot:
                snap_engine = RUNBOOK_ENGINES.get("snapshot_before_escalation")
                if snap_engine:
                    snap_out = snap_engine(
                        {"server_id": sid, "tag_prefix": "pre-resize", "reference_id": f"rightsizing-{actor}"},
                        False, actor
                    )
                    snap_result = snap_out.get("result", {}).get("snapshot_name", "n/a")

            # 5b. Stop if ACTIVE
            if was_active:
                r = client.session.post(
                    f"{client.nova_endpoint}/servers/{sid}/action",
                    headers=headers, json={"os-stop": None}
                )
                if r.status_code >= 300:
                    raise RuntimeError(f"Stop failed HTTP {r.status_code}")
                if not _poll_status(sid, "SHUTOFF", timeout=120):
                    raise RuntimeError("Timed out waiting for SHUTOFF")

            # 5c. Resize
            r = client.session.post(
                f"{client.nova_endpoint}/servers/{sid}/action",
                headers=headers, json={"resize": {"flavorRef": new_flavor_id}}
            )
            if r.status_code >= 300:
                raise RuntimeError(f"Resize failed HTTP {r.status_code}: {r.text[:200]}")
            if not _poll_status(sid, "VERIFY_RESIZE", timeout=300):
                raise RuntimeError("Timed out waiting for VERIFY_RESIZE")

            # 5d. Confirm resize
            r = client.session.post(
                f"{client.nova_endpoint}/servers/{sid}/action",
                headers=headers, json={"confirmResize": None}
            )
            if r.status_code >= 300:
                raise RuntimeError(f"confirmResize failed HTTP {r.status_code}")

            # 5e. Restart if was active
            if was_active:
                client.session.post(
                    f"{client.nova_endpoint}/servers/{sid}/action",
                    headers=headers, json={"os-start": None}
                )

            resized.append({
                "vm_id": sid,
                "vm_name": c["vm_name"],
                "old_flavor": c["current_flavor"]["name"],
                "new_flavor": c["suggested_flavor"]["name"],
                "savings_per_month": c["savings_per_month"],
                "snapshot_name": snap_result,
            })
            items_actioned += 1

        except Exception as e:
            logger.error(f"vm_rightsizing: resize {sid} failed: {e}")
            errors.append({"vm_id": sid, "vm_name": c["vm_name"], "error": str(e)})

    return {
        "result": {
            "candidates": candidates,
            "skipped": skipped,
            "resized": resized,
            "errors": errors,
            "total_candidates": len(candidates),
            "total_savings_per_month": total_savings,
            "currency": currency,
            "analysis_days": analysis_days,
            "mode": "executed",
        },
        "items_found": len(candidates),
        "items_actioned": items_actioned,
    }


# ===== Engine: capacity_forecast ==========================================

@register_engine("capacity_forecast")
def _engine_capacity_forecast(params: dict, dry_run: bool, actor: str) -> dict:
    """
    Run a linear-regression capacity forecast on hypervisor history data.
    Projects when vCPU / RAM usage will reach the warning threshold.

    Parameters
    ----------
    warn_days_threshold : alert if exhaustion projected within this many days (default 90)
    trigger_ticket      : if True, attempts to open a capacity ticket (default False)
    capacity_warn_pct   : capacity utilisation level treated as "exhaustion" (default 80)
    """
    warn_days = int(params.get("warn_days_threshold", 90))
    trigger_ticket = bool(params.get("trigger_ticket", False))
    warn_pct = float(params.get("capacity_warn_pct", 80.0))

    # ── 1. Pull weekly capacity snapshots from hypervisors_history ─────────
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        EXTRACT(EPOCH FROM DATE_TRUNC('week', recorded_at))::bigint AS week_epoch,
                        DATE_TRUNC('week', recorded_at)  AS week_start,
                        SUM(vcpus)                        AS total_vcpus,
                        SUM((raw_json::json->>'vcpus_used')::int)       AS used_vcpus,
                        SUM(memory_mb)                    AS total_ram_mb,
                        SUM((raw_json::json->>'memory_mb_used')::int)   AS used_ram_mb,
                        SUM(running_vms)                  AS total_running_vms,
                        COUNT(DISTINCT hypervisor_id)     AS hypervisor_count
                    FROM hypervisors_history
                    WHERE state = 'up'
                    GROUP BY DATE_TRUNC('week', recorded_at)
                    ORDER BY week_start
                """)
                rows = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"capacity_forecast: DB query failed: {e}")
        raise HTTPException(500, f"Capacity data query failed: {e}")

    if len(rows) < 2:
        return {
            "result": {
                "error": "Insufficient historical data for forecast (need ≥ 2 weekly snapshots)",
                "data_points": len(rows),
            },
            "items_found": 0,
            "items_actioned": 0,
        }

    # Convert to floats for regression
    epochs = [float(r["week_epoch"]) for r in rows]
    used_vcpus = [float(r["used_vcpus"] or 0) for r in rows]
    used_ram = [float(r["used_ram_mb"] or 0) for r in rows]

    # Total capacity (use the most recent row as representative)
    total_vcpus = float(rows[-1]["total_vcpus"] or 0)
    total_ram_mb = float(rows[-1]["total_ram_mb"] or 0)

    # ── 2. Simple numpy-free linear regression ─────────────────────────────
    def _linreg(x: list, y: list):
        """Returns (slope, intercept) for y = slope*x + intercept."""
        n = len(x)
        if n < 2:
            return 0.0, y[-1] if y else 0.0
        sx = sum(x)
        sy = sum(y)
        sxy = sum(xi * yi for xi, yi in zip(x, y))
        sxx = sum(xi * xi for xi in x)
        denom = n * sxx - sx * sx
        if denom == 0:
            return 0.0, sy / n
        slope = (n * sxy - sx * sy) / denom
        intercept = (sy - slope * sx) / n
        return slope, intercept

    slope_vcpu, intercept_vcpu = _linreg(epochs, used_vcpus)
    slope_ram, intercept_ram = _linreg(epochs, used_ram)

    # ── 3. Project exhaustion ──────────────────────────────────────────────
    now_epoch = float(rows[-1]["week_epoch"])
    secs_per_day = 86400.0

    def _days_to_limit(slope: float, intercept: float, current_epoch: float, limit: float) -> float:
        """Days until slope*x + intercept reaches limit. Returns inf if slope ≤ 0."""
        if slope <= 0:
            return float("inf")
        target_epoch = (limit - intercept) / slope
        return max(0.0, (target_epoch - current_epoch) / secs_per_day)

    vcpu_limit = total_vcpus * (warn_pct / 100.0)
    ram_limit = total_ram_mb * (warn_pct / 100.0)

    days_to_vcpu_warn = _days_to_limit(slope_vcpu, intercept_vcpu, now_epoch, vcpu_limit)
    days_to_ram_warn = _days_to_limit(slope_ram, intercept_ram, now_epoch, ram_limit)

    # Current utilisation
    current_used_vcpus = used_vcpus[-1] if used_vcpus else 0
    current_used_ram = used_ram[-1] if used_ram else 0
    current_vcpu_pct = round(current_used_vcpus / total_vcpus * 100, 1) if total_vcpus else 0
    current_ram_pct = round(current_used_ram / total_ram_mb * 100, 1) if total_ram_mb else 0

    # ── 4. Build result ────────────────────────────────────────────────────
    alerts = []
    if days_to_vcpu_warn != float("inf") and days_to_vcpu_warn <= warn_days:
        alerts.append({
            "dimension": "vcpus",
            "days_to_warn_threshold": round(days_to_vcpu_warn, 1),
            "current_used": int(current_used_vcpus),
            "total_capacity": int(total_vcpus),
            "current_pct": current_vcpu_pct,
            "warn_pct": warn_pct,
            "severity": "critical" if days_to_vcpu_warn < 30 else "warning",
        })
    if days_to_ram_warn != float("inf") and days_to_ram_warn <= warn_days:
        alerts.append({
            "dimension": "memory_mb",
            "days_to_warn_threshold": round(days_to_ram_warn, 1),
            "current_used_mb": int(current_used_ram),
            "total_capacity_mb": int(total_ram_mb),
            "current_pct": current_ram_pct,
            "warn_pct": warn_pct,
            "severity": "critical" if days_to_ram_warn < 30 else "warning",
        })

    # Weekly trend data for charts
    trend = [
        {
            "week": str(r["week_start"])[:10],
            "used_vcpus": int(r["used_vcpus"] or 0),
            "used_ram_mb": int(r["used_ram_mb"] or 0),
            "running_vms": int(r["total_running_vms"] or 0),
        }
        for r in rows
    ]

    forecast_result = {
        "alerts": alerts,
        "trend": trend,
        "capacity": {
            "total_vcpus": int(total_vcpus),
            "total_ram_mb": int(total_ram_mb),
            "hypervisor_count": int(rows[-1]["hypervisor_count"] or 0),
        },
        "current_utilisation": {
            "vcpus_used": int(current_used_vcpus),
            "vcpus_pct": current_vcpu_pct,
            "ram_used_mb": int(current_used_ram),
            "ram_pct": current_ram_pct,
        },
        "forecast": {
            "days_to_vcpu_warn": round(days_to_vcpu_warn, 1) if days_to_vcpu_warn != float("inf") else None,
            "days_to_ram_warn": round(days_to_ram_warn, 1) if days_to_ram_warn != float("inf") else None,
            "warn_pct": warn_pct,
            "warn_days_threshold": warn_days,
            "data_weeks": len(rows),
        },
    }

    # ── 5. Ticket stub ─────────────────────────────────────────────────────
    if trigger_ticket and alerts:
        logger.warning(
            "capacity_forecast: trigger_ticket=true but ticket system (T1) is not yet "
            "implemented — skipping ticket creation. Alerts: %s",
            [a["dimension"] for a in alerts],
        )
        forecast_result["ticket_status"] = "skipped — ticket system not yet available"

    return {
        "result": forecast_result,
        "items_found": len(alerts),
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
    """List runbook definitions.

    Admin and superadmin see all runbooks.
    All other roles see only runbooks that either have:
      - no dept visibility rows (unrestricted), OR
      - a visibility row matching the caller's department.
    """
    if isinstance(current_user, dict):
        username = current_user.get("username", "")
        role = current_user.get("role", "operator")
    else:
        username = current_user.username if hasattr(current_user, "username") else str(current_user)
        role = current_user.role if hasattr(current_user, "role") else "operator"

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Admin/superadmin bypass the dept filter
            if role in ("admin", "superadmin"):
                cur.execute("""
                    SELECT runbook_id, name, display_name, description, category,
                           risk_level, supports_dry_run, enabled,
                           parameters_schema, created_at, updated_at
                    FROM runbooks ORDER BY category, display_name
                """)
            else:
                # Resolve department for this user
                cur.execute(
                    "SELECT department_id FROM user_roles WHERE username = %s",
                    (username,)
                )
                user_row = cur.fetchone()
                dept_id = (user_row or {}).get("department_id")

                if dept_id is None:
                    # User has no dept — show only unrestricted runbooks
                    cur.execute("""
                        SELECT runbook_id, name, display_name, description, category,
                               risk_level, supports_dry_run, enabled,
                               parameters_schema, created_at, updated_at
                        FROM runbooks r
                        WHERE NOT EXISTS (
                            SELECT 1 FROM runbook_dept_visibility rdv
                            WHERE rdv.runbook_name = r.name
                        )
                        ORDER BY category, display_name
                    """)
                else:
                    cur.execute("""
                        SELECT runbook_id, name, display_name, description, category,
                               risk_level, supports_dry_run, enabled,
                               parameters_schema, created_at, updated_at
                        FROM runbooks r
                        WHERE (
                            -- No visibility restrictions = open to everyone
                            NOT EXISTS (
                                SELECT 1 FROM runbook_dept_visibility rdv
                                WHERE rdv.runbook_name = r.name
                            )
                            OR
                            -- Caller's dept is explicitly allowed
                            EXISTS (
                                SELECT 1 FROM runbook_dept_visibility rdv
                                WHERE rdv.runbook_name = r.name AND rdv.dept_id = %s
                            )
                        )
                        ORDER BY category, display_name
                    """, (dept_id,))
            rows = cur.fetchall()
    return [dict(r) for r in rows]


# ── Runbook dept visibility (admin) — must be declared BEFORE /{runbook_name} ──
@router.get("/visibility")
async def get_runbook_visibility(
    current_user=Depends(require_permission("runbooks", "admin")),
):
    """Return the full dept visibility matrix across all runbooks. Admin+ only."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, name FROM departments WHERE is_active = true ORDER BY sort_order"
            )
            departments = [dict(r) for r in cur.fetchall()]

            vis_map: Dict[str, List[int]] = {}
            try:
                cur.execute("SELECT runbook_name, dept_id FROM runbook_dept_visibility")
                for row in cur.fetchall():
                    vis_map.setdefault(row["runbook_name"], []).append(row["dept_id"])
            except Exception:
                pass  # Table may not exist yet on older installs

    return {"departments": departments, "visibility": vis_map}


@router.put("/visibility/{runbook_name}")
async def set_runbook_visibility(
    runbook_name: str,
    body: RunbookVisibilityUpdate,
    current_user=Depends(require_permission("runbooks", "admin")),
):
    """Replace the dept visibility list for one runbook.
    Empty dept_ids = unrestricted (visible to all depts).
    Admin+ only.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM runbooks WHERE name = %s", (runbook_name,))
            if not cur.fetchone():
                raise HTTPException(404, f"Runbook '{runbook_name}' not found")

            cur.execute(
                "DELETE FROM runbook_dept_visibility WHERE runbook_name = %s",
                (runbook_name,)
            )
            for dept_id in body.dept_ids:
                cur.execute(
                    "INSERT INTO runbook_dept_visibility (runbook_name, dept_id) "
                    "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (runbook_name, dept_id),
                )
        conn.commit()
    return {"runbook_name": runbook_name, "dept_ids": body.dept_ids}


# ── Lookup helpers — must be declared BEFORE /{runbook_name} ────────────────
@router.get("/lookup/vms")
async def lookup_vms(
    current_user=Depends(require_permission("runbooks", "read")),
):
    """Return a flat list of VMs from Nova for use in trigger-modal dropdowns."""
    from pf9_control import get_client
    try:
        client = get_client()
        client.authenticate()
        headers = {"X-Auth-Token": client.token}
        project_names = _resolve_project_names(client, headers)

        # Try all_tenants first (admin), fall back to tenant-scoped
        url = f"{client.nova_endpoint}/servers/detail?all_tenants=true&limit=500"
        resp = client.session.get(url, headers=headers)
        if resp.status_code == 403:
            url = f"{client.nova_endpoint}/servers/detail?limit=500"
            resp = client.session.get(url, headers=headers)
        resp.raise_for_status()

        servers = resp.json().get("servers", [])
        result = []
        for s in servers:
            pid = s.get("tenant_id", s.get("OS-EXT-STS:tenant_id", ""))
            result.append({
                "id": s.get("id"),
                "name": s.get("name", s.get("id")),
                "project_id": pid,
                "project_name": project_names.get(pid, pid),
                "status": s.get("status", "UNKNOWN"),
            })
        result.sort(key=lambda x: (x["project_name"], x["name"]))
        return result
    except Exception as e:
        logger.warning(f"lookup_vms failed: {e}")
        return []


@router.get("/lookup/projects")
async def lookup_projects(
    current_user=Depends(require_permission("runbooks", "read")),
):
    """Return a flat list of projects from Keystone for use in trigger-modal dropdowns."""
    from pf9_control import get_client
    try:
        client = get_client()
        client.authenticate()
        headers = {"X-Auth-Token": client.token}
        url = f"{client.keystone_endpoint}/projects?all_projects=true"
        resp = client.session.get(url, headers=headers)
        if resp.status_code == 403:
            url = f"{client.keystone_endpoint}/projects"
            resp = client.session.get(url, headers=headers)
        resp.raise_for_status()
        projects = resp.json().get("projects", [])
        result = [
            {"id": p["id"], "name": p.get("name", p["id"])}
            for p in projects
            if p.get("enabled", True)
        ]
        result.sort(key=lambda x: x["name"])
        return result
    except Exception as e:
        logger.warning(f"lookup_projects failed: {e}")
        return []


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
    if isinstance(user, dict):
        username = user.get("username", str(user))
        role = user.get("role", "operator")
    else:
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
