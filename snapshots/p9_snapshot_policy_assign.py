#!/usr/bin/env python3
"""
p9_snapshot_policy_assign.py

Automatically assign Cinder volume metadata for snapshot automation:

  auto_snapshot       = "true" / "false"
  snapshot_policies   = "daily_5,monthly_1st"
  retention_<policy>  = "<number>"   (e.g. retention_daily_5 = "5")

Decision is based on a JSON rules file (see snapshots/snapshot_policy_rules.json).
Works across ALL tenants using admin/service project scope.

Usage examples:

  # Dry run (see what would be updated, no writes)
  python snapshots/p9_snapshot_policy_assign.py --config snapshots/snapshot_policy_rules.json --dry-run

  # Real run, merge new policies with existing ones
  python snapshots/p9_snapshot_policy_assign.py --config snapshots/snapshot_policy_rules.json --merge-existing
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from p9_common import (
    CFG,
    get_session_best_scope,
    list_domains_all,
    list_projects_all,
    cinder_volumes_all,
    http_json,
    log_error,
    now_utc_str,
)


# --------------------------------------------------------------------
# Generic helpers
# --------------------------------------------------------------------


def is_blank(x) -> bool:
    return x is None or str(x).strip() == ""


def parse_policies(val) -> List[str]:
    """Parse comma/semicolon separated policy string into a list."""
    if not val:
        return []
    s = str(val).replace(";", ",")
    return [p.strip() for p in s.split(",") if p.strip()]


def bool_from_str(val) -> bool:
    return str(val).lower() in ("true", "1", "yes", "y")


def load_rules(path: str) -> List[Dict[str, Any]]:
    """
    Load rules JSON.

    Each rule structure:
      {
        "name": "Rule name",
        "priority": 100,
        "match": {
          "domain_name": "Default" | ["Default","Other"],
          "tenant_name": "service" | ["t1","t2"],
          "volume_name_prefix": "db_" | ["db_","sql-"],
          "volume_name_contains": "prod" | ["prod","important"],
          "bootable": true/false,
          "min_size_gb": 50,
          "max_size_gb": 500,
          "metadata_equals": {"env": "prod"},
          "metadata_contains": {"role": "db"}
        },
        "policies": ["daily_5","monthly_1st"],
        "auto_snapshot": true,
        "retention": {
          "daily_5": 5,
          "monthly_1st": 12
        }
      }
    """
    with open(path, "r", encoding="utf-8") as f:
        rules = json.load(f)

    if not isinstance(rules, list):
        raise ValueError("rules JSON must be a list of rule objects")

    for r in rules:
        r.setdefault("name", "unnamed-rule")
        r.setdefault("priority", 1000)
        r.setdefault("match", {})
        r.setdefault("policies", [])
        r.setdefault("retention", {})

    return rules


def match_value_list(val: str, cond) -> bool:
    """cond can be str or list; compares with val (case-sensitive simple match)."""
    if cond is None:
        return True
    if isinstance(cond, list):
        return val in cond
    return val == cond


def match_prefix(val: str, cond) -> bool:
    if cond is None:
        return True
    if isinstance(cond, list):
        return any(val.startswith(p) for p in cond)
    return val.startswith(cond)


def match_contains(val: str, cond) -> bool:
    if cond is None:
        return True
    if isinstance(cond, list):
        return any(c in val for c in cond)
    return cond in val


def metadata_matches_equals(meta: Dict[str, Any], cond: Dict[str, Any]) -> bool:
    """All key/value pairs in cond must match exactly in meta."""
    if not cond:
        return True
    for k, v in cond.items():
        if str(meta.get(k)) != str(v):
            return False
    return True


def metadata_matches_contains(meta: Dict[str, Any], cond: Dict[str, Any]) -> bool:
    """All key/substring pairs in cond must be found in meta[key]."""
    if not cond:
        return True
    for k, v in cond.items():
        val = str(meta.get(k, ""))
        if isinstance(v, list):
            if not any(str(sub) in val for sub in v):
                return False
        else:
            if str(v) not in val:
                return False
    return True


def rule_matches(rule: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    """
    ctx fields:
      domain_name, tenant_name, volume_name, bootable (bool),
      size_gb (int), metadata (dict)
    """
    m = rule.get("match", {})

    # domain_name
    if "domain_name" in m:
        if not match_value_list(ctx["domain_name"], m["domain_name"]):
            return False

    # tenant_name
    if "tenant_name" in m:
        if not match_value_list(ctx["tenant_name"], m["tenant_name"]):
            return False

    # volume_name_prefix
    if "volume_name_prefix" in m:
        if not match_prefix(ctx["volume_name"], m["volume_name_prefix"]):
            return False

    # volume_name_contains
    if "volume_name_contains" in m:
        if not match_contains(ctx["volume_name"], m["volume_name_contains"]):
            return False

    # bootable
    if "bootable" in m:
        if bool(m["bootable"]) != ctx["bootable"]:
            return False

    # size bounds
    if "min_size_gb" in m:
        if ctx["size_gb"] is not None and ctx["size_gb"] < int(m["min_size_gb"]):
            return False

    if "max_size_gb" in m:
        if ctx["size_gb"] is not None and ctx["size_gb"] > int(m["max_size_gb"]):
            return False

    # metadata equals / contains
    if "metadata_equals" in m:
        if not metadata_matches_equals(ctx["metadata"], m["metadata_equals"]):
            return False

    if "metadata_contains" in m:
        if not metadata_matches_contains(ctx["metadata"], m["metadata_contains"]):
            return False

    return True


def decide_policies_for_volume(
    ctx: Dict[str, Any],
    rules: List[Dict[str, Any]],
) -> Tuple[Any, List[str], Dict[str, int], List[str]]:
    """
    Returns:
      (auto_snapshot_target, policies_target, retention_map, matched_rule_names)

    auto_snapshot_target:
      - True / False: explicitly set
      - None: do not change auto_snapshot

    policies_target:
      - [] or list of policies (if empty & auto_snapshot_target is None -> no change)

    retention_map:
      - dict policy_name -> days (int)
      - only for policies that had retention in one or more matching rules.
        If multiple rules set retention for the same policy, the LAST matching
        rule by priority wins (higher priority = lower number).
    """
    wanted_policies = set()
    retention_map: Dict[str, int] = {}
    auto_snapshot_target = None
    matched_rules: List[str] = []

    for rule in sorted(rules, key=lambda r: r.get("priority", 1000)):
        if not rule_matches(rule, ctx):
            continue

        matched_rules.append(rule["name"])

        for p in rule.get("policies", []):
            wanted_policies.add(p)

        if "auto_snapshot" in rule:
            auto_snapshot_target = bool(rule["auto_snapshot"])

        # Retention overrides for this rule
        for pol, days in rule.get("retention", {}).items():
            try:
                retention_map[pol] = int(days)
            except Exception:
                # Ignore invalid retention values, just log
                msg = f"Invalid retention '{days}' for policy '{pol}' in rule '{rule['name']}'"
                print("    WARNING:", msg)
                log_error("policy_assign/retention", msg)

    if not matched_rules:
        return None, [], {}, []

    return auto_snapshot_target, sorted(wanted_policies), retention_map, matched_rules


def update_volume_metadata(
    session,
    project_id: str,
    volume_id: str,
    new_meta: Dict[str, str],
    dry_run: bool,
):
    """
    POST /v3/{project_id}/volumes/{volume_id}/metadata

    NOTE: project_id should be the *scoped* admin/service project
    (the same one used for cinder_volumes_all and snapshot creation),
    not the tenant's own project_id. This allows an admin token to
    update metadata across all tenants.
    """
    url = f"{CFG['REGION_URL']}/cinder/v3/{project_id}/volumes/{volume_id}/metadata"
    payload = {"metadata": new_meta}
    if dry_run:
        print(f"    DRY-RUN: would POST {url} payload={payload}")
        return
    try:
        http_json(session, "POST", url, json=payload)
    except Exception as e:
        msg = f"Failed to update metadata for volume {volume_id}: {type(e).__name__}: {e}"
        print("    ERROR:", msg)
        log_error("policy_assign/metadata", msg)


# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------


def main():
    default_rules_path = os.path.join(os.path.dirname(__file__), "snapshot_policy_rules.json")

    parser = argparse.ArgumentParser(
        description="Assign snapshot metadata (auto_snapshot, snapshot_policies, retention_*) "
        "to Cinder volumes based on rules."
    )
    parser.add_argument(
        "--config",
        default=default_rules_path,
        help=(
            "Path to rules JSON (default: snapshots/snapshot_policy_rules.json)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change but do not update metadata.",
    )
    parser.add_argument(
        "--merge-existing",
        action="store_true",
        help="Merge new policies with existing snapshot_policies (default: replace).",
    )

    args = parser.parse_args()

    rules = load_rules(args.config)
    print(f"[1/4] Loaded {len(rules)} rule(s) from {args.config}")

    print("[2/4] Keystone auth (project scope)...")
    session, token, auth_body, scope, _ = get_session_best_scope()
    admin_project_id = auth_body["token"]["project"]["id"]
    print(f"      Scope: {scope}, project={admin_project_id}")

    print("[3/4] Fetching domains and projects...")
    domains = list_domains_all(session)
    projects = list_projects_all(session)

    domain_name_by_id = {d.get("id"): d.get("name") for d in domains}
    projects_by_id = {p.get("id"): p for p in projects}

    print(f"      Domains: {len(domains)}, Projects: {len(projects)}")

    print("[4/4] Fetching volumes (all tenants via admin project)...")
    vols = cinder_volumes_all(session, admin_project_id)
    print(f"      Total volumes: {len(vols)}")

    changed = 0
    skipped = 0

    for v in vols:
        vol_id = v.get("id")
        tenant_project_id = v.get("os-vol-tenant-attr:tenant_id") or v.get("project_id")

        proj = projects_by_id.get(tenant_project_id, {})
        tenant_name = proj.get("name") or tenant_project_id
        domain_name = domain_name_by_id.get(proj.get("domain_id"), proj.get("domain_id"))

        vol_name = v.get("name") or vol_id
        size_gb = v.get("size")
        bootable = bool_from_str(v.get("bootable"))
        metadata = v.get("metadata") or {}

        ctx = {
            "domain_name": domain_name or "",
            "tenant_name": tenant_name or "",
            "volume_name": str(vol_name),
            "size_gb": int(size_gb) if size_gb is not None else None,
            "bootable": bootable,
            "metadata": metadata,
        }

        auto_current = bool_from_str(metadata.get("auto_snapshot", "false"))
        existing_policies = parse_policies(
            metadata.get("snapshot_policies") or metadata.get("snapshot_policy")
        )

        auto_target, policies_target, retention_map, matched_rules = decide_policies_for_volume(
            ctx, rules
        )

        if auto_target is None and not policies_target and not retention_map:
            # No rule matched -> leave volume as is
            skipped += 1
            continue

        # Determine final auto_snapshot
        if auto_target is None:
            auto_final = auto_current
        else:
            auto_final = auto_target

        # Determine final policies list
        if args.merge_existing and existing_policies:
            policies_final = sorted(set(existing_policies) | set(policies_target))
        else:
            policies_final = policies_target

        auto_final_str = "true" if auto_final else "false"
        policies_final_str = ",".join(policies_final)

        # Current values as strings
        current_auto_str = str(metadata.get("auto_snapshot", "")).lower()
        current_policies_str = (
            metadata.get("snapshot_policies")
            or metadata.get("snapshot_policy")
            or ""
        )

        # Prepare new metadata dict based on existing
        new_meta = dict(metadata)
        new_meta["auto_snapshot"] = auto_final_str
        if policies_final:
            new_meta["snapshot_policies"] = policies_final_str

        # Apply retention metadata for policies we have retention rules for
        for pol, days in retention_map.items():
            key = f"retention_{pol}"
            new_meta[key] = str(days)

        # Detect if anything actually changes
        def retention_str_for_policies(meta_dict: Dict[str, Any], policies: List[str]) -> str:
            parts = []
            for p in sorted(policies):
                key = f"retention_{p}"
                if key in meta_dict:
                    parts.append(f"{key}={meta_dict[key]}")
            return ";".join(parts)

        before_ret = retention_str_for_policies(metadata, policies_final)
        after_ret = retention_str_for_policies(new_meta, policies_final)

        if (
            current_auto_str == auto_final_str
            and current_policies_str == policies_final_str
            and before_ret == after_ret
        ):
            skipped += 1
            continue

        print(f"\n[Volume] {vol_id} ({vol_name})")
        print(f"  Tenant: {tenant_name} / Domain: {domain_name}")
        print(f"  Size: {size_gb} GB, Bootable: {bootable}")
        print(f"  Rules matched: {', '.join(matched_rules) if matched_rules else 'NONE'}")
        print(f"  auto_snapshot: {current_auto_str or '-'} -> {auto_final_str}")
        print(f"  policies:      {current_policies_str or '-'} -> {policies_final_str or '-'}")
        if retention_map:
            print(f"  retention:     {before_ret or '-'} -> {after_ret or '-'}")

        # IMPORTANT: use admin_project_id for the Cinder v3 URL, so admin token can
        # update metadata across all tenants.
        update_volume_metadata(session, admin_project_id, vol_id, new_meta, args.dry_run)
        changed += 1

    print("\nSummary:")
    print(f"  Volumes processed:  {len(vols)}")
    print(f"  Volumes changed:    {changed}")
    print(f"  Volumes unchanged:  {skipped}")
    print(f"  Finished at (UTC):  {now_utc_str()}")


if __name__ == "__main__":
    main()
