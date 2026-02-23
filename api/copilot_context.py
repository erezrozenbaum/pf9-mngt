"""
copilot_context.py — Infrastructure context builder for LLM tiers.

Queries key DB tables and builds a concise text summary that is injected
into the LLM system prompt.  When ``redact=True`` (default for external
LLMs), hostnames, IPs, user emails and API keys are masked.
"""

from __future__ import annotations

import re
from typing import Optional

from db_pool import get_connection
from psycopg2.extras import RealDictCursor


# ---------------------------------------------------------------------------
# Redaction helpers
# ---------------------------------------------------------------------------

_IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_KEY_RE = re.compile(r"(sk-|ak-|AKIA|ghp_|glpat-|xox[bpsa]-)[A-Za-z0-9_\-]{8,}")


def redact_text(text: str) -> str:
    """Mask IPs, emails and API-key-like strings."""
    text = _IP_RE.sub("[REDACTED_IP]", text)
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = _KEY_RE.sub("[REDACTED_KEY]", text)
    return text


def redact_hostname(name: Optional[str]) -> str:
    if not name:
        return "host-***"
    parts = name.split(".")
    return parts[0][:3] + "***" if parts else "host-***"


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def build_infra_context(redact: bool = False) -> str:
    """
    Return a multi-line text string summarising the current infrastructure.
    Suitable for injection into an LLM system/user prompt.
    """
    sections: list[str] = []

    try:
        with get_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # --- Counts ---------------------------------------------------
            cur.execute("""
                SELECT
                  (SELECT COUNT(*) FROM domains)      AS domains,
                  (SELECT COUNT(*) FROM projects)     AS projects,
                  (SELECT COUNT(*) FROM hypervisors)  AS hosts,
                  (SELECT COUNT(*) FROM servers)      AS vms,
                  (SELECT COUNT(*) FROM volumes)      AS volumes,
                  (SELECT COUNT(*) FROM networks)     AS networks,
                  (SELECT COUNT(*) FROM images)       AS images,
                  (SELECT COUNT(*) FROM snapshots)    AS snapshots
            """)
            c = cur.fetchone()
            sections.append(
                f"INVENTORY: {c['domains']} domains, {c['projects']} projects, "
                f"{c['hosts']} hosts, {c['vms']} VMs, {c['volumes']} volumes, "
                f"{c['networks']} networks, {c['images']} images, {c['snapshots']} snapshots."
            )

            # --- Capacity --------------------------------------------------
            cur.execute("""
                SELECT SUM(vcpus) AS total_vcpus,
                       SUM(COALESCE((raw_json->>'vcpus_used')::int, 0)) AS used_vcpus,
                       SUM(memory_mb) AS total_mb,
                       SUM(COALESCE((raw_json->>'memory_mb_used')::int, 0)) AS used_mb,
                       SUM(local_gb) AS total_gb,
                       SUM(COALESCE((raw_json->>'local_gb_used')::int, 0)) AS used_gb
                FROM hypervisors
            """)
            cap = cur.fetchone()
            if cap and cap["total_vcpus"]:
                sections.append(
                    f"CAPACITY: vCPU {cap['used_vcpus']}/{cap['total_vcpus']}, "
                    f"RAM {round((cap['used_mb'] or 0)/1024,1)}/{round((cap['total_mb'] or 0)/1024,1)} GB, "
                    f"Disk {cap['used_gb']}/{cap['total_gb']} GB."
                )

            # --- Host list -------------------------------------------------
            cur.execute("""
                SELECT hostname, state, status, vcpus, memory_mb
                FROM hypervisors ORDER BY hostname LIMIT 20
            """)
            hosts = cur.fetchall()
            if hosts:
                lines = []
                for h in hosts:
                    hn = redact_hostname(h["hostname"]) if redact else (h["hostname"] or "?")
                    lines.append(
                        f"  {hn}: state={h['state']}, status={h['status']}, "
                        f"vcpus={h['vcpus']}, ram={h['memory_mb']}MB"
                    )
                sections.append("HOSTS:\n" + "\n".join(lines))

            # --- Error VMs -------------------------------------------------
            cur.execute("""
                SELECT s.name, s.status, s.vm_state, p.name AS project
                FROM servers s LEFT JOIN projects p ON s.project_id = p.id
                WHERE UPPER(s.status) IN ('ERROR','SHUTOFF','SUSPENDED')
                LIMIT 15
            """)
            err_vms = cur.fetchall()
            if err_vms:
                lines = []
                for v in err_vms:
                    vn = v["name"] or "unnamed"
                    if redact:
                        vn = vn[:4] + "***"
                    lines.append(f"  {vn}: status={v['status']}, project={v['project'] or '?'}")
                sections.append(f"PROBLEM VMs ({len(err_vms)}):\n" + "\n".join(lines))
            else:
                sections.append("PROBLEM VMs: none — all VMs are in normal state.")

            # --- Recent drift events ---------------------------------------
            cur.execute("""
                SELECT COUNT(*) AS cnt,
                       COUNT(*) FILTER (WHERE severity = 'critical') AS critical
                FROM drift_events
            """)
            dr = cur.fetchone()
            sections.append(
                f"DRIFT: {dr['cnt']} event(s), {dr['critical']} critical."
            )

            # --- Snapshots / compliance ------------------------------------
            cur.execute("""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status = 'available') AS available
                FROM snapshots
            """)
            sn = cur.fetchone()
            sections.append(
                f"SNAPSHOTS: {sn['total']} total, {sn['available']} available."
            )

            # --- OS distribution -------------------------------------------
            cur.execute("""
                SELECT COALESCE(LOWER(os_distro), 'unknown') AS os, COUNT(*) AS cnt
                FROM servers
                GROUP BY COALESCE(LOWER(os_distro), 'unknown')
                ORDER BY cnt DESC
                LIMIT 15
            """)
            os_rows = cur.fetchall()
            if os_rows:
                parts = [f"{r['os']}={r['cnt']}" for r in os_rows]
                sections.append(f"OS DISTRIBUTION: {', '.join(parts)}.")

            # --- Recent activity (last 5) ----------------------------------
            cur.execute("""
                SELECT username, action, resource_type, resource_name
                FROM activity_log ORDER BY created_at DESC LIMIT 5
            """)
            acts = cur.fetchall()
            if acts:
                lines = []
                for a in acts:
                    un = "[REDACTED]" if redact else (a["username"] or "?")
                    lines.append(
                        f"  {un} → {a['action']} {a['resource_type']} {a['resource_name'] or ''}"
                    )
                sections.append("RECENT ACTIVITY:\n" + "\n".join(lines))

    except Exception as exc:
        sections.append(f"[context build error: {exc}]")

    full_text = "\n\n".join(sections)
    if redact:
        full_text = redact_text(full_text)
    return full_text
