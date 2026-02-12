import ast
import json
import os
from datetime import datetime, timezone

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values


"""
p9_snapshot_compliance_report.py

Builds a snapshot compliance report from a pf9_rvtools Excel export.

Expected sheets in pf9_rvtools workbook (as produced by pf9_rvtools.py):
  - Volumes
  - Snapshots
  - Tenants
  - Domains
  - Servers
  - Ports
  - Networks

Output workbook sheets:
  1) VolumeSnapshotCompliance   - one row per volume, detailed status
  2) TenantComplianceSummary    - aggregated view by tenant
  3) DomainComplianceSummary    - aggregated view by domain
  4) PolicyComplianceSummary    - aggregated view by snapshot policy
  5) SnapshotDetails            - all snapshots, enriched with tenant/domain
  6) AllVolumes                 - all volumes with basic info (for reference)

Compliance rules (per volume):
  - auto_snapshot metadata must be true/yes/1
  - A matching policy must exist in snapshot_policies or snapshot_policy
  - last_snapshot_at is not older than SLA (sla_days; default 2)
  - For this script we do NOT enforce "count of snapshots >= retention";
    retention is handled by the snapshot creation script itself.

Metadata conventions on Volumes sheet:
  - "metadata" column: JSON or Python dict literal with keys like:
        {
          "auto_snapshot": "true",
          "snapshot_policies": "daily_5,monthly_1st",
          "retention_daily_5": "5"
        }
  - Backwards compatible fields:
        "snapshot_policy" (single value)
        "retention" (global)

Snapshot/volume mapping:
  - A snapshot row must have a "volume_id" that matches Volumes.id
  - Snapshot metadata may contain "policy" and "created_by".
"""


def parse_metadata_field(val):
    """
    Parse metadata stored as either:
      - JSON string
      - Python dict literal string
      - Already a dict
      - NaN / None

    Returns a dict (possibly empty on error).
    """
    if val is None:
        return {}
    if isinstance(val, dict):
        return val
    if isinstance(val, float):
        # NaN, etc.
        return {}
    s = str(val).strip()
    if not s or s in ("{}", "nan", "NaN"):
        return {}
    # Try JSON first
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # Try Python literal (e.g. "{'k': 'v'}")
    try:
        obj = ast.literal_eval(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    return {}


def normalize_bool(val):
    """
    Return a boolean based on a loose string match:
      true / yes / 1 => True
      false / no / 0 / "" / None => False
    """
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ("true", "yes", "1")


def parse_policies_from_metadata(meta: dict):
    """
    Extract a list of policy names from volume metadata.

    Supports:
      - "snapshot_policies": "daily_5,monthly_1st"   (comma-separated)
      - "snapshot_policy": "daily_5"                (single value)
    """
    policies = []

    # New multi-policy field
    multi = meta.get("snapshot_policies")
    if isinstance(multi, str) and multi.strip():
        for p in multi.split(","):
            p = p.strip()
            if p:
                policies.append(p)
    elif isinstance(multi, (list, tuple)):
        for p in multi:
            s = str(p).strip()
            if s:
                policies.append(s)

    # Legacy single-policy fallback
    if not policies:
        single = meta.get("snapshot_policy")
        if single:
            policies.append(str(single).strip())

    return policies


def get_db_connection():
    """Get database connection using environment variables."""
    return psycopg2.connect(
        host=os.getenv("PF9_DB_HOST", "db"),
        port=int(os.getenv("PF9_DB_PORT", "5432")),
        database=os.getenv("PF9_DB_NAME", "pf9_mgmt"),
        user=os.getenv("PF9_DB_USER", "pf9"),
        password=os.getenv("PF9_DB_PASSWORD", "")
    )


def write_compliance_to_db(vol_comp: pd.DataFrame, input_file: str, output_file: str, sla_days: int):
    """Write compliance report data to database tables.

    Creates one row per volume × policy (splitting the comma-separated
    policy string from the DataFrame).  Resolves tenant/domain and VM
    names from the DB so that compliance_details is fully populated.
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Count compliant vs non-compliant
        compliant_count = int(vol_comp["is_compliant"].sum()) if not vol_comp.empty else 0
        total_volumes = len(vol_comp)
        noncompliant_count = total_volumes - compliant_count

        # Insert compliance report summary
        cur.execute("""
            INSERT INTO compliance_reports
            (report_date, input_file, output_file, sla_days, total_volumes, compliant_count, noncompliant_count)
            VALUES (NOW(), %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (input_file, output_file, sla_days, total_volumes, compliant_count, noncompliant_count))

        report_id = cur.fetchone()[0]

        # ---- Build lookup maps from DB for enrichment ----------------------
        # project_id → (project_name, domain_id, domain_name)
        project_map = {}
        try:
            cur.execute("""
                SELECT p.id, p.name AS project_name,
                       p.domain_id, d.name AS domain_name
                FROM projects p
                LEFT JOIN domains d ON d.id = p.domain_id
            """)
            for prow in cur.fetchall():
                project_map[prow[0]] = {
                    "project_name": prow[1],
                    "domain_id": prow[2],
                    "domain_name": prow[3],
                }
        except Exception:
            pass

        # volume_id → (volume_name, vm_id, vm_name) from volumes + servers
        volume_enrichment = {}
        try:
            cur.execute("""
                SELECT v.id,
                       v.name AS volume_name,
                       v.raw_json->'attachments'->0->>'server_id' AS vm_id,
                       srv.name AS vm_name,
                       v.raw_json->'metadata' AS metadata
                FROM volumes v
                LEFT JOIN servers srv
                    ON srv.id = v.raw_json->'attachments'->0->>'server_id'
            """)
            for vrow in cur.fetchall():
                volume_enrichment[vrow[0]] = {
                    "volume_name": vrow[1] if vrow[1] else None,
                    "vm_id": vrow[2],
                    "vm_name": vrow[3],
                    "metadata": vrow[4] if vrow[4] else {},
                }
        except Exception:
            pass

        # ---- Prepare compliance detail rows --------------------------------
        if not vol_comp.empty:
            details = []
            for _, row in vol_comp.iterrows():
                volume_id = row.get("volume_id")
                project_id = row.get("project_id")

                # Resolve names from DB lookups
                vol_info = volume_enrichment.get(volume_id, {})
                proj_info = project_map.get(project_id, {})

                # Volume name: prefer DB name, fall back to DataFrame, skip NaN
                raw_vol_name = row.get("volume_name")
                if pd.isna(raw_vol_name) or str(raw_vol_name).strip().lower() in ("nan", ""):
                    raw_vol_name = None
                vol_name = vol_info.get("volume_name") or raw_vol_name

                # Tenant = domain (project→domain)
                tenant_id = proj_info.get("domain_id") or row.get("domain_id")
                tenant_name = proj_info.get("domain_name") or row.get("domain_name")
                if pd.isna(tenant_name):
                    tenant_name = None

                # Project name
                project_name = proj_info.get("project_name") or row.get("project_name")
                if pd.isna(project_name):
                    project_name = None

                # Domain
                domain_id = proj_info.get("domain_id") or row.get("domain_id")
                if pd.isna(domain_id):
                    domain_id = None
                domain_name = proj_info.get("domain_name") or row.get("domain_name")
                if pd.isna(domain_name):
                    domain_name = None

                # VM info
                vm_id = vol_info.get("vm_id") or (row.get("vm_id") if pd.notna(row.get("vm_id")) else None)
                vm_name = vol_info.get("vm_name") or (row.get("vm_name") if pd.notna(row.get("vm_name")) else None)

                # Last snapshot
                last_snapshot_at = None
                if pd.notna(row.get("last_snapshot_at")):
                    last_snapshot_at = row["last_snapshot_at"]

                days_since = None
                if pd.notna(row.get("days_since_last_snapshot")):
                    days_since = float(row["days_since_last_snapshot"])
                elif pd.notna(row.get("last_snapshot_age_days")):
                    days_since = float(row["last_snapshot_age_days"])

                is_compliant = bool(row.get("is_compliant", False))
                compliance_status = row.get("status", "Unknown")
                if pd.isna(compliance_status):
                    compliance_status = "Compliant" if is_compliant else "Missing"

                # Split comma-separated policies into individual rows
                policies_str = str(row.get("policy", "")) if pd.notna(row.get("policy")) else ""
                policies = [p.strip() for p in policies_str.split(",") if p.strip()]
                if not policies:
                    policies = ["unknown"]

                # Get per-policy retention from volume metadata
                vol_metadata = vol_info.get("metadata", {})
                if isinstance(vol_metadata, str):
                    try:
                        vol_metadata = json.loads(vol_metadata)
                    except Exception:
                        vol_metadata = {}

                for policy_name in policies:
                    ret_key = f"retention_{policy_name}"
                    try:
                        retention = int(vol_metadata.get(ret_key, 0))
                    except (TypeError, ValueError):
                        retention = 0

                    details.append((
                        report_id,
                        volume_id,
                        vol_name,
                        tenant_id,
                        tenant_name,
                        project_id,
                        project_name,
                        domain_id,
                        domain_name,
                        vm_id,
                        vm_name,
                        policy_name,
                        retention,
                        last_snapshot_at,
                        days_since,
                        is_compliant,
                        compliance_status,
                    ))

            # Bulk insert compliance details
            execute_values(cur, """
                INSERT INTO compliance_details
                (report_id, volume_id, volume_name, tenant_id, tenant_name, project_id, project_name,
                 domain_id, domain_name, vm_id, vm_name, policy_name, retention_days, last_snapshot_at,
                 days_since_snapshot, is_compliant, compliance_status)
                VALUES %s
            """, details)

        conn.commit()
        cur.close()
        conn.close()

        print(f"✅ Compliance data written to database (report ID: {report_id}, {len(details) if not vol_comp.empty else 0} detail rows)")
        return report_id
        
    except Exception as e:
        print(f"⚠️  Failed to write to database: {e}")
        return None


def get_retention_for_policy(meta: dict, policy_name: str, default: int = 7) -> int:
    """
    Determine retention for a given volume+policy based on metadata.

    Priority:
      1) retention_<policy_name>
      2) snapshot_retention_<policy_name>
      3) retention
      4) default
    """
    key1 = f"retention_{policy_name}"
    key2 = f"snapshot_retention_{policy_name}"

    val = meta.get(key1) or meta.get(key2) or meta.get("retention") or default
    try:
        return int(str(val))
    except Exception:
        return default


def load_rvtools_data(path: str):
    """
    Load the pf9_rvtools Excel workbook and return dataframes as a dict.
    We expect specific sheet names; missing sheets are replaced with empty
    frames so the script can still run with partial data.
    """
    xls = pd.ExcelFile(path)

    def safe_read(sheet_name):
        if sheet_name in xls.sheet_names:
            return pd.read_excel(xls, sheet_name)
        else:
            return pd.DataFrame()

    data = {
        "volumes": safe_read("Volumes"),
        "snapshots": safe_read("Snapshots"),
        "tenants": safe_read("Tenants"),
        "domains": safe_read("Domains"),
        "servers": safe_read("Servers"),
        "ports": safe_read("Ports"),
        "networks": safe_read("Networks"),
    }
    return data


def find_latest_snapshot_for_volume(snapshots_df: pd.DataFrame, volume_id: str):
    """
    Return (last_snapshot_at, last_snap_row, total_snaps_for_volume)
    where last_snapshot_at is a timezone-naive datetime (UTC), or None.
    """
    if snapshots_df.empty:
        return None, None, 0

    snaps = snapshots_df[snapshots_df["volume_id"] == volume_id]
    if snaps.empty:
        return None, None, 0

    snaps = snaps.copy()
    # Normalize created_at column
    if "created_at" in snaps.columns:
        snaps["created_at"] = pd.to_datetime(
            snaps["created_at"], utc=True, errors="coerce"
        )
    else:
        snaps["created_at"] = pd.NaT

    snaps = snaps.dropna(subset=["created_at"])
    if snaps.empty:
        return None, None, 0

    snaps = snaps.sort_values("created_at", ascending=False)
    last_row = snaps.iloc[0]
    last_dt_utc = last_row["created_at"]
    if pd.isna(last_dt_utc):
        last_dt_utc = None
    else:
        # Convert to timezone-naive for Excel compatibility
        last_dt_utc = last_dt_utc.to_pydatetime().replace(tzinfo=None)

    return last_dt_utc, last_row, len(snaps)


def build_snapshot_details_sheet(
    snapshots_df: pd.DataFrame,
    volumes_df: pd.DataFrame,
    tenants_df: pd.DataFrame,
    domains_df: pd.DataFrame,
):
    """
    Returns a dataframe where each snapshot row is enriched with:
      domain_name, project_name, volume_name, volume_size_gb
    """
    if snapshots_df.empty:
        return pd.DataFrame()

    vols_small = volumes_df[["id", "name", "size", "os-vol-tenant-attr:tenant_id"]].copy()
    vols_small.rename(
        columns={
            "id": "volume_id",
            "name": "volume_name",
            "size": "volume_size_gb",
            "os-vol-tenant-attr:tenant_id": "project_id",
        },
        inplace=True,
    )

    snap_enriched = snapshots_df.merge(
        vols_small, on="volume_id", how="left", suffixes=("", "_vol")
    )

    # Add tenant/project name
    proj_map = {}
    if not tenants_df.empty:
        if "project_id" in tenants_df.columns:
            pid_col = "project_id"
        elif "id" in tenants_df.columns:
            pid_col = "id"
        else:
            pid_col = None

        if pid_col:
            for _, row in tenants_df.iterrows():
                pid = row.get(pid_col)
                pname = row.get("project_name") or row.get("name")
                if pid:
                    proj_map[pid] = pname

    snap_enriched["project_name"] = snap_enriched["project_id"].map(proj_map)

    # Add domain name
    domain_map = {}
    if not domains_df.empty:
        for _, row in domains_df.iterrows():
            did = row.get("id")
            dname = row.get("name")
            if did:
                domain_map[did] = dname

    if not tenants_df.empty:
        # we assume Tenants sheet has project_id -> domain_id
        proj_domain_map = {}
        for _, row in tenants_df.iterrows():
            pid = row.get("project_id") or row.get("id")
            did = row.get("domain_id")
            if pid and did:
                proj_domain_map[pid] = did

        snap_enriched["domain_id"] = snap_enriched["project_id"].map(
            proj_domain_map
        )
        snap_enriched["domain_name"] = snap_enriched["domain_id"].map(domain_map)
    else:
        snap_enriched["domain_id"] = None
        snap_enriched["domain_name"] = None

    # Normalize created_at
    if "created_at" in snap_enriched.columns:
        snap_enriched["created_at"] = pd.to_datetime(
            snap_enriched["created_at"], utc=True, errors="coerce"
        ).dt.tz_localize(None)

    return snap_enriched


def build_volume_compliance(
    data: dict,
    sla_default_days: int = 2,
):
    """
    Build the main VolumeSnapshotCompliance dataframe.

    Each row represents a volume and includes:
      - tenant/domain info
      - volume metadata (auto_snapshot, snapshot_policies, retention, etc.)
      - last snapshot info (timestamp, age in days, policy if present)
      - is_compliant flag
    """
    volumes_df = data["volumes"].copy()
    snapshots_df = data["snapshots"].copy()
    tenants_df = data["tenants"].copy()
    domains_df = data["domains"].copy()

    if volumes_df.empty:
        return pd.DataFrame()

    # Build project -> domain & tenant maps
    proj_to_tenant = {}
    proj_to_domain = {}
    if not tenants_df.empty:
        for _, row in tenants_df.iterrows():
            pid = row.get("project_id") or row.get("id")
            pname = row.get("project_name") or row.get("name")
            did = row.get("domain_id")
            if pid:
                proj_to_tenant[pid] = pname
                proj_to_domain[pid] = did

    domain_id_to_name = {}
    if not domains_df.empty:
        for _, row in domains_df.iterrows():
            did = row.get("id")
            dname = row.get("name")
            if did:
                domain_id_to_name[did] = dname

    rows = []
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    # Pre-normalize snapshots timestamps
    if not snapshots_df.empty and "created_at" in snapshots_df.columns:
        snapshots_df["created_at"] = pd.to_datetime(
            snapshots_df["created_at"], utc=True, errors="coerce"
        )

    for _, v in volumes_df.iterrows():
        vol_id = v.get("id")
        vol_name = v.get("name")
        vol_size = v.get("size")
        vol_status = v.get("status")
        vol_bootable = v.get("bootable")

        # Tenant / domain info
        project_id = v.get("os-vol-tenant-attr:tenant_id") or v.get("project_id")
        project_name = proj_to_tenant.get(project_id)
        domain_id = proj_to_domain.get(project_id)
        domain_name = domain_id_to_name.get(domain_id)

        # Parse metadata
        meta_raw = v.get("metadata")
        meta = parse_metadata_field(meta_raw)
        auto_snap = normalize_bool(meta.get("auto_snapshot"))

        policies = parse_policies_from_metadata(meta)
        policies_str = ",".join(policies)
        # For SLA we use either sla_days metadata or default
        sla_days_raw = meta.get("sla_days")
        try:
            sla_days = int(str(sla_days_raw)) if sla_days_raw is not None else sla_default_days
        except Exception:
            sla_days = sla_default_days

        # Last snapshot for this volume
        last_snap_at, last_snap_row, total_snaps = find_latest_snapshot_for_volume(
            snapshots_df, vol_id
        )

        if last_snap_at is not None:
            age_days = (now_utc - last_snap_at).total_seconds() / 86400.0
        else:
            age_days = None

        # Determine policy of the last snapshot (if metadata present)
        last_policy = None
        last_created_by = None
        if last_snap_row is not None:
            snap_meta_raw = last_snap_row.get("metadata")
            snap_meta = parse_metadata_field(snap_meta_raw)
            last_policy = snap_meta.get("policy") or snap_meta.get("snapshot_policy")
            last_created_by = snap_meta.get("created_by")

        # Compliance logic
        if not auto_snap:
            is_compliant = False
        elif not policies:
            is_compliant = False
        elif last_snap_at is None:
            is_compliant = False
        else:
            # Check age
            is_compliant = age_days is not None and age_days <= sla_days

        rows.append(
            {
                "domain_name": domain_name,
                "project_name": project_name,
                "project_id": project_id,
                "volume_id": vol_id,
                "volume_name": vol_name,
                "volume_size_gb": vol_size,
                "volume_status": vol_status,
                "bootable": vol_bootable,
                "auto_snapshot": auto_snap,
                "policy": policies_str,
                "policy_type": determine_policy_type(policies),
                "sla_days": sla_days,
                "last_snapshot_at": last_snap_at,
                "last_snapshot_age_days": age_days,
                "snapshots_count": total_snaps,
                "last_snapshot_policy": last_policy,
                "last_snapshot_created_by": last_created_by,
                "is_compliant": bool(is_compliant),
            }
        )

    df = pd.DataFrame(rows)
    return df


def determine_policy_type(policies: list[str]):
    """
    Return a simple "type" label for a set of policies.
    e.g.:
      ["daily_5"] -> "daily"
      ["monthly_1st"] -> "monthly"
      ["daily_5","monthly_1st"] -> "mixed"
    """
    if not policies:
        return ""

    has_daily = any("daily" in p for p in policies)
    has_monthly = any("monthly" in p for p in policies)
    has_weekly = any("weekly" in p for p in policies)

    kinds = []
    if has_daily:
        kinds.append("daily")
    if has_weekly:
        kinds.append("weekly")
    if has_monthly:
        kinds.append("monthly")

    if len(kinds) == 1:
        return kinds[0]
    if len(kinds) > 1:
        return "mixed"
    return ",".join(policies)


def build_tenant_compliance_summary(vol_comp: pd.DataFrame):
    """
    Summarize compliance at tenant (project) level.

    For each (domain_name, project_name, project_id) we show:
      - total_volumes
      - compliant_volumes
      - non_compliant_volumes
      - compliance_ratio
    """
    if vol_comp.empty:
        return pd.DataFrame()

    grp = vol_comp.groupby(
        ["domain_name", "project_name", "project_id"], dropna=False
    )

    rows = []
    for (domain, project, pid), df in grp:
        total = len(df)
        compliant = int(df["is_compliant"].sum())
        non_compliant = total - compliant
        ratio = compliant / total if total else 0.0

        rows.append(
            {
                "domain_name": domain,
                "project_name": project,
                "project_id": pid,
                "total_volumes": total,
                "compliant_volumes": compliant,
                "non_compliant_volumes": non_compliant,
                "compliance_ratio": ratio,
            }
        )

    return pd.DataFrame(rows).sort_values(
        ["domain_name", "project_name", "project_id"]
    )


def build_domain_compliance_summary(vol_comp: pd.DataFrame):
    """
    Summarize compliance at domain level.
    """
    if vol_comp.empty:
        return pd.DataFrame()

    grp = vol_comp.groupby(["domain_name"], dropna=False)

    rows = []
    for domain, df in grp:
        total = len(df)
        compliant = int(df["is_compliant"].sum())
        non_compliant = total - compliant
        ratio = compliant / total if total else 0.0

        rows.append(
            {
                "domain_name": domain,
                "total_volumes": total,
                "compliant_volumes": compliant,
                "non_compliant_volumes": non_compliant,
                "compliance_ratio": ratio,
            }
        )

    return pd.DataFrame(rows).sort_values(["domain_name"])


def build_policy_compliance_summary(vol_comp: pd.DataFrame):
    """
    Summarize compliance per policy token.
    Since a volume may have multiple policies in the "policy" column,
    we split by comma and explode.
    """
    if vol_comp.empty:
        return pd.DataFrame()

    df = vol_comp.copy()
    df["policy_list"] = df["policy"].fillna("").apply(
        lambda s: [p.strip() for p in str(s).split(",") if p.strip()]
    )

    df = df.explode("policy_list")
    df = df[df["policy_list"].notna() & (df["policy_list"] != "")]
    if df.empty:
        return pd.DataFrame()

    grp = df.groupby("policy_list")

    rows = []
    for policy, g in grp:
        total = len(g)
        compliant = int(g["is_compliant"].sum())
        non_compliant = total - compliant
        ratio = compliant / total if total else 0.0

        rows.append(
            {
                "policy": policy,
                "total_volumes": total,
                "compliant_volumes": compliant,
                "non_compliant_volumes": non_compliant,
                "compliance_ratio": ratio,
            }
        )

    return pd.DataFrame(rows).sort_values(["policy"])


def build_all_volumes_sheet(data: dict):
    """
    Build a generic AllVolumes sheet for reference (all volumes, even
    if auto_snapshot is not enabled).
    """
    volumes_df = data["volumes"].copy()
    tenants_df = data["tenants"].copy()
    domains_df = data["domains"].copy()

    if volumes_df.empty:
        return pd.DataFrame()

    # Build project -> tenant / domain
    proj_to_tenant = {}
    proj_to_domain = {}
    if not tenants_df.empty:
        for _, row in tenants_df.iterrows():
            pid = row.get("project_id") or row.get("id")
            pname = row.get("project_name") or row.get("name")
            did = row.get("domain_id")
            if pid:
                proj_to_tenant[pid] = pname
                proj_to_domain[pid] = did

    domain_id_to_name = {}
    if not domains_df.empty:
        for _, row in domains_df.iterrows():
            did = row.get("id")
            dname = row.get("name")
            if did:
                domain_id_to_name[did] = dname

    rows = []
    for _, v in volumes_df.iterrows():
        vol_id = v.get("id")
        vol_name = v.get("name")
        vol_size = v.get("size")
        vol_status = v.get("status")
        vol_bootable = v.get("bootable")
        project_id = v.get("os-vol-tenant-attr:tenant_id") or v.get("project_id")
        project_name = proj_to_tenant.get(project_id)
        domain_id = proj_to_domain.get(project_id)
        domain_name = domain_id_to_name.get(domain_id)

        meta = parse_metadata_field(v.get("metadata"))
        auto_snap = normalize_bool(meta.get("auto_snapshot"))
        policies = parse_policies_from_metadata(meta)
        policies_str = ",".join(policies)

        rows.append(
            {
                "domain_name": domain_name,
                "project_name": project_name,
                "project_id": project_id,
                "volume_id": vol_id,
                "volume_name": vol_name,
                "volume_size_gb": vol_size,
                "volume_status": vol_status,
                "bootable": vol_bootable,
                "auto_snapshot": auto_snap,
                "policy": policies_str,
                "raw_metadata": v.get("metadata"),
            }
        )

    return pd.DataFrame(rows)


def main(input_path: str | None = None, output_path: str | None = None):
    if input_path is None:
        # If not provided, pick the latest pf9_rvtools_*.xlsx from the
        # default report directory /mnt/reports (which maps to C:\Reports\Platform9).
        default_dir = "/mnt/reports"
        search_dir = default_dir if os.path.isdir(default_dir) else "."
        latest = None
        latest_mtime = None
        for name in os.listdir(search_dir):
            if not name.lower().endswith(".xlsx"):
                continue
            if not name.startswith("p9_rvtools_"):
                continue
            path = os.path.join(search_dir, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if latest is None or mtime > latest_mtime:
                latest = path
                latest_mtime = mtime

        if latest is None:
            raise SystemExit(
                "No pf9_rvtools_*.xlsx found. Please specify --input or place a report in "
                f"{search_dir}."
            )

        input_path = latest

    if output_path is None:
        base_dir = os.path.dirname(os.path.abspath(input_path))
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%SZ")
        output_path = os.path.join(
            base_dir, f"snapshot_compliance_{ts}.xlsx"
        )

    print(f"Input : {input_path}")
    print(f"Output: {output_path}")

    data = load_rvtools_data(input_path)
    vol_comp = build_volume_compliance(data)
    tenant_summary = build_tenant_compliance_summary(vol_comp)
    domain_summary = build_domain_compliance_summary(vol_comp)
    policy_summary = build_policy_compliance_summary(vol_comp)
    snapshot_details = build_snapshot_details_sheet(
        data["snapshots"], data["volumes"], data["tenants"], data["domains"]
    )
    all_volumes = build_all_volumes_sheet(data)

    # Ensure all datetime columns are timezone-naive for Excel
    if not vol_comp.empty and "last_snapshot_at" in vol_comp.columns:
        vol_comp["last_snapshot_at"] = pd.to_datetime(
            vol_comp["last_snapshot_at"], errors="coerce"
        ).dt.tz_localize(None)

    if not snapshot_details.empty and "created_at" in snapshot_details.columns:
        snapshot_details["created_at"] = pd.to_datetime(
            snapshot_details["created_at"], errors="coerce"
        ).dt.tz_localize(None)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        vol_comp.to_excel(writer, "VolumeSnapshotCompliance", index=False)
        tenant_summary.to_excel(writer, "TenantComplianceSummary", index=False)
        domain_summary.to_excel(writer, "DomainComplianceSummary", index=False)
        policy_summary.to_excel(writer, "PolicyComplianceSummary", index=False)
        snapshot_details.to_excel(writer, "SnapshotDetails", index=False)
        all_volumes.to_excel(writer, "AllVolumes", index=False)

    print("Done.")
    
    # Write compliance data to database
    sla_days = int(os.getenv("COMPLIANCE_REPORT_SLA_DAYS", "2"))
    write_compliance_to_db(vol_comp, input_path, output_path, sla_days)


def _cli():
    import argparse

    parser = argparse.ArgumentParser(
        description="Build snapshot compliance report from pf9_rvtools Excel output."
    )
    parser.add_argument(
        "--input",
        "-i",
        default=None,
        help=(
            "Path to pf9_rvtools_*.xlsx. If omitted, the script will pick the "
            "latest pf9_rvtools_*.xlsx from C:\\Reports\\Platform9 (or current dir)."
        ),
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help=(
            "Output Excel path. If omitted, a timestamped snapshot_compliance_*.xlsx "
            "will be created next to the input file."
        ),
    )

    args = parser.parse_args()
    main(args.input, args.output)


if __name__ == "__main__":
    main()
