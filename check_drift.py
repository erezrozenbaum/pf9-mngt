import psycopg2
import os
import json
from pathlib import Path

# Load .env file if present (so this script works standalone on the host)
env_path = Path(__file__).resolve().parent / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)

try:
    c = psycopg2.connect(
        host=os.getenv('PF9_DB_HOST', 'localhost'),
        port=int(os.getenv('PF9_DB_PORT', '5432')),
        dbname=os.getenv('PF9_DB_NAME', 'pf9_mgmt'),
        user=os.getenv('PF9_DB_USER', 'pf9'),
        password=os.getenv('PF9_DB_PASSWORD', os.getenv('POSTGRES_PASSWORD', ''))
    )
    cur = c.cursor()
    cur.execute("SELECT COUNT(*) FROM networks WHERE status IS NOT NULL")
    print(f"NET_STATUS_COUNT={cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM ports WHERE status IS NOT NULL")
    print(f"PORT_STATUS_COUNT={cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM subnets WHERE enable_dhcp IS NOT NULL")
    print(f"SUBNET_DHCP_COUNT={cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM volumes WHERE server_id IS NOT NULL")
    print(f"VOL_SERVER_COUNT={cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM drift_rules")
    print(f"DRIFT_RULES={cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM drift_events")
    print(f"DRIFT_EVENTS={cur.fetchone()[0]}")

    # ---------------------------------------------------------------------------
    # Inventory version diff — "what changed since last week?" (E7)
    # Compares the most recent snapshot against the nearest one 7 days earlier.
    # ---------------------------------------------------------------------------
    print("")
    print("=== INVENTORY CHANGE SUMMARY (last 7 days) ===")

    # Fetch the two boundary snapshots
    cur.execute(
        "SELECT id, collected_at, snapshot FROM inventory_snapshots "
        "ORDER BY collected_at DESC LIMIT 1"
    )
    snap_latest = cur.fetchone()

    snap_week = None
    if snap_latest:
        cur.execute(
            "SELECT id, collected_at, snapshot FROM inventory_snapshots "
            "WHERE collected_at <= (NOW() - INTERVAL '7 days') "
            "ORDER BY collected_at DESC LIMIT 1"
        )
        snap_week = cur.fetchone()

    if not snap_latest:
        print("  No inventory snapshots recorded yet. Run POST /admin/inventory/refresh first.")
    elif not snap_week:
        print("  Only one snapshot available (less than 7 days of history).")
        counts = snap_latest[2].get("counts", {})
        print(f"  Latest snapshot ({snap_latest[1].strftime('%Y-%m-%d %H:%M UTC')}): "
              f"{counts.get('servers', 0)} servers, "
              f"{counts.get('projects', 0)} projects, "
              f"{counts.get('volumes', 0)} volumes")
    else:
        latest_ts = snap_latest[1].strftime('%Y-%m-%d %H:%M UTC')
        week_ts = snap_week[1].strftime('%Y-%m-%d %H:%M UTC')
        print(f"  Comparing: {week_ts}  →  {latest_ts}")
        print("")

        fd = snap_week[2]
        td = snap_latest[2]

        # Servers
        from_srv = {s["id"]: s for s in fd.get("servers", [])}
        to_srv = {s["id"]: s for s in td.get("servers", [])}
        added_srv = set(to_srv) - set(from_srv)
        removed_srv = set(from_srv) - set(to_srv)
        changed_srv = []
        for sid in set(from_srv) & set(to_srv):
            before, after = from_srv[sid], to_srv[sid]
            delta = {k: (before.get(k), after.get(k))
                     for k in ("status", "flavor_id", "hypervisor_hostname")
                     if before.get(k) != after.get(k)}
            if delta:
                changed_srv.append((sid, after.get("name"), delta))

        print(f"  SERVERS: +{len(added_srv)} added, -{len(removed_srv)} removed, {len(changed_srv)} changed")
        for sid in list(added_srv)[:5]:
            s = to_srv[sid]
            print(f"    + {s.get('name', sid)} (project={s.get('project_id', '?')})")
        if len(added_srv) > 5:
            print(f"    ... and {len(added_srv) - 5} more")
        for sid in list(removed_srv)[:5]:
            s = from_srv[sid]
            print(f"    - {s.get('name', sid)} (project={s.get('project_id', '?')})")
        if len(removed_srv) > 5:
            print(f"    ... and {len(removed_srv) - 5} more")
        for sid, name, delta in changed_srv[:5]:
            changes_str = ", ".join(f"{k}: {v[0]}→{v[1]}" for k, v in delta.items())
            print(f"    ~ {name or sid}: {changes_str}")
        if len(changed_srv) > 5:
            print(f"    ... and {len(changed_srv) - 5} more")

        # Projects
        from_proj = {p["id"] for p in fd.get("projects", [])}
        to_proj = {p["id"]: p for p in td.get("projects", [])}
        added_proj = set(to_proj) - from_proj
        removed_proj = from_proj - set(to_proj)
        print(f"  PROJECTS: +{len(added_proj)} added, -{len(removed_proj)} removed")
        for pid in list(added_proj)[:5]:
            print(f"    + {to_proj[pid].get('name', pid)}")

        # Volumes
        from_vol = {v["id"] for v in fd.get("volumes", [])}
        to_vol_map = {v["id"]: v for v in td.get("volumes", [])}
        added_vol = set(to_vol_map) - from_vol
        removed_vol = from_vol - set(to_vol_map)
        print(f"  VOLUMES:  +{len(added_vol)} added, -{len(removed_vol)} removed")

        # Resource count summary
        fc, tc = fd.get("counts", {}), td.get("counts", {})
        print("")
        print("  Resource counts:")
        for resource in ("servers", "projects", "volumes", "networks"):
            f_cnt = fc.get(resource, "?")
            t_cnt = tc.get(resource, "?")
            delta_str = ""
            if isinstance(f_cnt, int) and isinstance(t_cnt, int):
                diff = t_cnt - f_cnt
                delta_str = f"  ({'+' if diff >= 0 else ''}{diff})"
            print(f"    {resource:12s}: {f_cnt} → {t_cnt}{delta_str}")

    c.close()
except Exception as e:
    print(f"ERROR: {e}")

