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
        with get_connection() as conn, \
             conn.cursor(cursor_factory=RealDictCursor) as cur:

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

            # --- Recent operational events (warning + critical, last 5) ---
            cur.execute("""
                SELECT oe.title, oe.severity, oe.category, oe.entity_name,
                       oe.actor, oe.occurred_at
                FROM operational_events oe
                WHERE oe.severity IN ('warning', 'critical')
                ORDER BY oe.occurred_at DESC
                LIMIT 5
            """)
            op_events = cur.fetchall()
            if op_events:
                lines = []
                for ev in op_events:
                    actor_part = f" by {ev['actor']}" if ev["actor"] else ""
                    lines.append(
                        f"  [{ev['occurred_at']}] {ev['severity'].upper()} "
                        f"{ev['category']}: {ev['title']}"
                        f" (entity={ev['entity_name'] or '?'}{actor_part})"
                    )
                sections.append(
                    "RECENT OPERATIONAL EVENTS (warning/critical):\n" + "\n".join(lines)
                )

            # --- Open operational insights (top 10 by severity) -----------
            try:
                cur.execute("""
                    SELECT severity, type, entity_name, entity_id,
                           title, metadata
                    FROM operational_insights
                    WHERE status = 'open'
                    ORDER BY
                        CASE severity
                            WHEN 'critical' THEN 1
                            WHEN 'high'     THEN 2
                            WHEN 'medium'   THEN 3
                            ELSE 4
                        END,
                        detected_at DESC
                    LIMIT 10
                """)
                ins_rows = cur.fetchall()
                if ins_rows:
                    from collections import Counter
                    sev_counts = Counter(r["severity"] for r in ins_rows)
                    sev_summary = ", ".join(
                        f"{sev_counts.get(s, 0)} {s}"
                        for s in ("critical", "high", "medium", "low")
                        if sev_counts.get(s, 0) > 0
                    )
                    top_lines = []
                    for r in ins_rows[:5]:
                        name = r["entity_name"] or r["entity_id"] or "?"
                        if redact:
                            name = name[:3] + "***"
                        meta = r["metadata"] or {}
                        extra = ""
                        if "runway_days" in meta:
                            extra = f" runway={meta['runway_days']}d"
                        elif "confidence" in meta:
                            extra = f" conf={meta['confidence']}"
                        top_lines.append(
                            f"  [{r['severity'].upper()}] {r['type']} on {name}{extra}: {r['title']}"
                        )
                    sections.append(
                        f"OPEN INSIGHTS ({sev_summary}):\n" + "\n".join(top_lines)
                    )
                else:
                    sections.append("OPEN INSIGHTS: none currently open.")
            except Exception:
                pass

            # --- Tenant health scores (worst 3 + declining) ----------------
            try:
                cur.execute("""
                    SELECT ths.project_id,
                           ths.score,
                          ths.security_posture,
                           p.name AS project_name,
                           prev.score AS prev_score
                    FROM tenant_health_scores ths
                    JOIN projects p ON p.id = ths.project_id
                    LEFT JOIN LATERAL (
                        SELECT score FROM tenant_health_scores t2
                        WHERE t2.project_id = ths.project_id
                          AND t2.computed_at < ths.computed_at
                        ORDER BY t2.computed_at DESC LIMIT 1
                    ) prev ON true
                    WHERE ths.computed_at = (
                        SELECT MAX(t3.computed_at) FROM tenant_health_scores t3
                        WHERE t3.project_id = ths.project_id
                    )
                    ORDER BY ths.score ASC
                    LIMIT 10
                """)
                hs_rows = cur.fetchall()
                if hs_rows:
                    lines = []
                    # worst 3 overall + any declining by >10 pts
                    shown = set()
                    for r in hs_rows[:3]:
                        pn = r["project_name"] or r["project_id"]
                        if redact:
                            pn = pn[:3] + "***"
                        trend = ""
                        if r["prev_score"] is not None:
                            delta = r["score"] - r["prev_score"]
                            trend = f" ({'↓' if delta < 0 else '↑'}{abs(delta)})"
                        sec = r.get("security_posture")
                        sec_txt = f" sec={sec}" if sec is not None else ""
                        lines.append(f"  {pn}={r['score']}{trend}{sec_txt}")
                        shown.add(r["project_id"])
                    for r in hs_rows:
                        if r["project_id"] in shown:
                            continue
                        if r["prev_score"] is not None and (r["prev_score"] - r["score"]) >= 10:
                            pn = r["project_name"] or r["project_id"]
                            if redact:
                                pn = pn[:3] + "***"
                            sec = r.get("security_posture")
                            sec_txt = f" sec={sec}" if sec is not None else ""
                            lines.append(f"  {pn}={r['score']}{sec_txt} (↓{r['prev_score'] - r['score']} this cycle — declining)")
                    sections.append("TENANT HEALTH SCORES (worst/declining):\n" + "\n".join(lines))
            except Exception:
                pass

            # --- Recent anomalies (last 24 h) ------------------------------
            try:
                cur.execute("""
                    SELECT type, entity_name, entity_id, severity, detected_at,
                           metadata
                    FROM operational_insights
                    WHERE type LIKE 'anomaly%'
                      AND detected_at >= NOW() - INTERVAL '24 hours'
                    ORDER BY detected_at DESC
                    LIMIT 8
                """)
                anoms = cur.fetchall()
                if anoms:
                    lines = []
                    for a in anoms:
                        name = a["entity_name"] or a["entity_id"] or "?"
                        if redact:
                            name = name[:3] + "***"
                        lines.append(
                            f"  {a['type']} on {name} [{a['severity']}]"
                        )
                    sections.append(
                        f"RECENT ANOMALIES (24h — {len(anoms)} detected):\n"
                        + "\n".join(lines)
                    )
            except Exception:
                pass

            # --- SLA at risk (open capacity insights on SLA tenants) -------
            try:
                cur.execute("""
                    SELECT DISTINCT p.name AS project_name,
                           sc.tier,
                           oi.type AS insight_type,
                           oi.metadata
                    FROM sla_commitments sc
                    JOIN projects p ON p.id = sc.tenant_id
                    JOIN operational_insights oi
                         ON oi.entity_id = sc.tenant_id
                         AND oi.entity_type = 'project'
                         AND oi.type LIKE 'capacity%'
                         AND oi.status = 'open'
                    WHERE sc.effective_to IS NULL
                    ORDER BY sc.tier DESC
                    LIMIT 5
                """)
                sla_rows = cur.fetchall()
                if sla_rows:
                    lines = []
                    for r in sla_rows:
                        pn = r["project_name"] or "?"
                        if redact:
                            pn = pn[:3] + "***"
                        meta = r["metadata"] or {}
                        runway = meta.get("runway_days")
                        runway_str = f", runway={runway}d" if runway else ""
                        lines.append(
                            f"  {pn} ({r['tier']} SLA): {r['insight_type']}{runway_str}"
                        )
                    sections.append(
                        "SLA AT RISK (capacity insights on SLA tenants):\n"
                        + "\n".join(lines)
                    )
            except Exception:
                pass

    except Exception as exc:
        sections.append(f"[context build error: {exc}]")

    full_text = "\n\n".join(sections)
    if redact:
        full_text = redact_text(full_text)
    return full_text
