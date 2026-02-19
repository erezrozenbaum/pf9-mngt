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
