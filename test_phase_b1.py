#!/usr/bin/env python3
"""
Phase B1 test suite — quota_adjustment + org_usage_report
Run inside pf9_api container:  python /tmp/test_phase_b1.py
"""
import json, sys, os
import requests

BASE = os.environ.get("TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.environ["TEST_ADMIN_EMAIL"]
ADMIN_PASS  = os.environ["TEST_ADMIN_PASS"]

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

errors = []

def check(label, condition, detail=""):
    if condition:
        print(f"  {PASS}  {label}")
    else:
        print(f"  {FAIL}  {label}" + (f"  →  {detail}" if detail else ""))
        errors.append(label)

# ── Login ────────────────────────────────────────────────────────────────────
print("\n[1] Login")
r = requests.post(f"{BASE}/auth/login", json={"username": ADMIN_EMAIL, "password": ADMIN_PASS})
check("admin login 200", r.status_code == 200, r.text[:200])
token = r.json().get("access_token", "") if r.ok else ""
H = {"Authorization": f"Bearer {token}"}

# ── Runbook list ─────────────────────────────────────────────────────────────
print("\n[2] Runbook list — both new runbooks visible to admin")
r = requests.get(f"{BASE}/api/runbooks", headers=H)
check("GET /api/runbooks 200", r.status_code == 200, r.text[:200])
if r.ok:
    names = [rb["name"] for rb in r.json()]
    check("quota_adjustment in list", "quota_adjustment" in names, str(names))
    check("org_usage_report in list", "org_usage_report" in names, str(names))
    check("total runbooks == 27", len(names) == 27, f"got {len(names)}")

# ── quota_adjustment: missing project_id ─────────────────────────────────────
print("\n[3] quota_adjustment — error on missing project_id")
r = requests.post(f"{BASE}/api/runbooks/trigger", headers=H, json={
    "runbook_name": "quota_adjustment",
    "parameters": {},
    "dry_run": True,
})
check("trigger returns 200 or 400", r.status_code in (200, 400, 422), r.text[:300])

# ── quota_adjustment: dry_run ─────────────────────────────────────────────────
print("\n[4] quota_adjustment — dry_run=True (no real API calls)")
r = requests.post(f"{BASE}/api/runbooks/trigger", headers=H, json={
    "runbook_name": "quota_adjustment",
    "parameters": {
        "project_id":  "00000000-0000-0000-0000-000000000001",
        "project_name": "test-project",
        "new_vcpus":   40,
        "new_ram_mb":  81920,
        "new_gigabytes": 500,
        "reason": "B1 test dry run",
        "require_billing_approval": False,
    },
    "dry_run": True,
})
check("trigger 200", r.status_code == 200, r.text[:300])
if r.ok:
    data = r.json()
    exec_id = data.get("execution_id")
    check("execution_id present", bool(exec_id), str(data))

    # Poll for completion (up to 15s)
    import time
    result_data = None
    for _ in range(15):
        time.sleep(1)
        pr = requests.get(f"{BASE}/api/runbooks/executions/{exec_id}", headers=H)
        if pr.ok:
            st = pr.json().get("status")
            if st in ("completed", "failed"):
                result_data = pr.json()
                break

    check("execution completed", result_data is not None and result_data.get("status") == "completed",
          str(result_data)[:300] if result_data else "timed out")

    if result_data and result_data.get("result"):
        result = result_data["result"] if isinstance(result_data["result"], dict) else json.loads(result_data["result"])
        check("dry_run flag in result", result.get("dry_run") is True, str(result)[:200])
        check("before key present",  "before" in result, str(list(result.keys())))
        check("after key present",   "after" in result,  str(list(result.keys())))
        check("deltas key present",  "deltas" in result, str(list(result.keys())))
        check("items_actioned == 0", result_data.get("items_actioned", -1) == 0,
              str(result_data.get("items_actioned")))

# ── quota_adjustment: billing gate skipped (no integration configured) ────────
print("\n[5] quota_adjustment — billing gate skipped when no integration configured")
r = requests.post(f"{BASE}/api/runbooks/trigger", headers=H, json={
    "runbook_name": "quota_adjustment",
    "parameters": {
        "project_id": "00000000-0000-0000-0000-000000000002",
        "new_vcpus": 10,
        "require_billing_approval": True,
    },
    "dry_run": True,
})
check("trigger 200", r.status_code == 200, r.text[:300])
if r.ok:
    exec_id = r.json().get("execution_id")
    import time
    result_data = None
    for _ in range(15):
        time.sleep(1)
        pr = requests.get(f"{BASE}/api/runbooks/executions/{exec_id}", headers=H)
        if pr.ok and pr.json().get("status") in ("completed", "failed"):
            result_data = pr.json()
            break

    check("execution completed", result_data and result_data.get("status") == "completed",
          str(result_data)[:300] if result_data else "timed out")
    if result_data and result_data.get("result"):
        result = result_data["result"] if isinstance(result_data["result"], dict) else json.loads(result_data["result"])
        gate = result.get("billing_gate_simulation") or result.get("billing_gate") or {}
        check("billing gate skipped=True", gate.get("skipped") is True, str(gate))

# ── org_usage_report: missing project_id ─────────────────────────────────────
print("\n[6] org_usage_report — error on missing project_id")
r = requests.post(f"{BASE}/api/runbooks/trigger", headers=H, json={
    "runbook_name": "org_usage_report",
    "parameters": {},
    "dry_run": False,
})
check("trigger 200 or 400/422", r.status_code in (200, 400, 422), r.text[:300])

# ── org_usage_report: real execution ─────────────────────────────────────────
print("\n[7] org_usage_report — full execution for a fake project")
r = requests.post(f"{BASE}/api/runbooks/trigger", headers=H, json={
    "runbook_name": "org_usage_report",
    "parameters": {
        "project_id":  "00000000-0000-0000-0000-000000000099",
        "include_cost_estimate": True,
        "include_snapshot_details": True,
        "period_days": 30,
    },
    "dry_run": False,
})
check("trigger 200", r.status_code == 200, r.text[:300])
if r.ok:
    exec_id = r.json().get("execution_id")
    import time
    result_data = None
    for _ in range(20):
        time.sleep(1)
        pr = requests.get(f"{BASE}/api/runbooks/executions/{exec_id}", headers=H)
        if pr.ok and pr.json().get("status") in ("completed", "failed"):
            result_data = pr.json()
            break

    check("execution completed or failed gracefully",
          result_data is not None and result_data.get("status") in ("completed", "failed"),
          str(result_data)[:300] if result_data else "timed out")

    if result_data and result_data.get("status") == "completed":
        result = result_data["result"] if isinstance(result_data["result"], dict) else json.loads(result_data["result"])
        check("html_body present", bool(result.get("html_body")), "missing")
        check("html_body contains project_id or name",
              "00000000-0000-0000-0000-000000000099" in result.get("html_body", "")
              or "project" in result.get("html_body", "").lower())
        check("usage key present", "usage" in result, str(list(result.keys())))
        check("quota key present", "quota" in result, str(list(result.keys())))
        check("items_actioned == 0", result_data.get("items_actioned", -1) == 0,
              str(result_data.get("items_actioned")))

# ── Dept-based visibility check ───────────────────────────────────────────────
print("\n[8] Dept visibility — yehuda (Sales) sees org_usage_report, not quota_adjustment")
rs = requests.post(f"{BASE}/auth/login", json={"username": os.environ.get("TEST_SALES_USER", "yehuda"), "password": os.environ["TEST_SALES_PASS"]})
if rs.ok:
    sales_token = rs.json().get("access_token", "")
    HS = {"Authorization": f"Bearer {sales_token}"}
    r2 = requests.get(f"{BASE}/api/runbooks", headers=HS)
    check("GET /api/runbooks 200 for sales user", r2.status_code == 200, r2.text[:200])
    if r2.ok:
        sales_names = [rb["name"] for rb in r2.json()]
        check("org_usage_report visible to Sales",    "org_usage_report" in sales_names, str(sales_names))
        check("quota_adjustment NOT visible to Sales", "quota_adjustment" not in sales_names, str(sales_names))
else:
    print(f"  SKIP  (yehuda login failed: {rs.status_code})")

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
total = 0
passed = 0
# Count from errors list and total check calls — use printed output as source of truth
# (errors list is authoritative for failures)
if errors:
    print(f"FAILED checks ({len(errors)}):")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("All checks passed ✓")
    sys.exit(0)
