#!/usr/bin/env python3
"""
Operational Intelligence test suite  —  v1.85.0
Set TEST_PF9_LIVE=1 plus TEST_ADMIN_EMAIL/TEST_ADMIN_PASS to run against a live stack.
"""
import os

import pytest
import requests

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_PF9_LIVE"),
    reason="requires TEST_PF9_LIVE=1 and a live PF9 endpoint",
)


def test_intelligence():  # noqa: C901
    BASE  = os.environ.get("TEST_BASE_URL", "http://localhost:8000")
    EMAIL = os.environ["TEST_ADMIN_EMAIL"]
    PASSW = os.environ["TEST_ADMIN_PASS"]

    PASS = "\033[92mPASS\033[0m"
    FAIL = "\033[91mFAIL\033[0m"
    INFO = "\033[94mINFO\033[0m"

    errors: list[str] = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        if condition:
            print(f"  {PASS}  {label}")
        else:
            msg = f"  {FAIL}  {label}" + (f"  \u2192  {detail}" if detail else "")
            print(msg)
            errors.append(label)

    def info(msg: str) -> None:
        print(f"  {INFO}  {msg}")

    # ── [0] Login ─────────────────────────────────────────────────────────────
    print("\n[0] Login")
    r = requests.post(f"{BASE}/auth/login", json={"username": EMAIL, "password": PASSW})
    check("Login 200", r.status_code == 200, r.text[:120])
    token = r.json().get("token", "")
    hdrs  = {"Authorization": f"Bearer {token}"}

    # ── [1] Insights list ─────────────────────────────────────────────────────
    print("\n[1] Insights list")
    r = requests.get(f"{BASE}/api/intelligence/insights", headers=hdrs)
    check("GET /api/intelligence/insights 200", r.status_code == 200, r.text[:120])
    body = r.json()
    check("Response has 'insights' list", "insights" in body)
    check("Response has 'total'",         "total"    in body)
    check("Response has 'page'",          "page"     in body)
    info(f"  Total active insights: {body.get('total', '?')}")

    # ── [2] Summary ───────────────────────────────────────────────────────────
    print("\n[2] Insights summary")
    r = requests.get(f"{BASE}/api/intelligence/insights/summary", headers=hdrs)
    check("GET /api/intelligence/insights/summary 200", r.status_code == 200, r.text[:120])
    summary = r.json()
    check("by_severity in summary",  "by_severity"  in summary)
    check("total_open in summary",   "total_open"   in summary)
    check("by_type in summary",      "by_type"      in summary)
    info(f"  Summary: {summary.get('by_severity', {})}")

    # ── [3] Severity filter ───────────────────────────────────────────────────
    print("\n[3] Severity filter")
    for sev in ("critical", "high", "medium", "low"):
        r = requests.get(f"{BASE}/api/intelligence/insights?severity={sev}", headers=hdrs)
        check(f"GET insights?severity={sev} 200", r.status_code == 200)
        items = r.json().get("insights", [])
        if items:
            check(f"All returned items are {sev}", all(i["severity"] == sev for i in items))

    # ── [4] Type filter ───────────────────────────────────────────────────────
    print("\n[4] Type filter")
    for itype in ("capacity_storage", "waste_idle_vm", "risk_snapshot_gap"):
        r = requests.get(f"{BASE}/api/intelligence/insights?type={itype}", headers=hdrs)
        check(f"GET insights?type={itype} 200", r.status_code == 200)

    # ── [5] 404 on unknown id ─────────────────────────────────────────────────
    print("\n[5] Single insight 404")
    r = requests.get(f"{BASE}/api/intelligence/insights/999999999", headers=hdrs)
    check("GET unknown insight id returns 404", r.status_code == 404)

    # ── [6] Lifecycle on first open insight ───────────────────────────────────
    print("\n[6] Lifecycle: ack → snooze → resolve")
    r = requests.get(f"{BASE}/api/intelligence/insights?status=open&page_size=1", headers=hdrs)
    open_insights = r.json().get("insights", [])
    if not open_insights:
        info("  No open insights found; skipping lifecycle test")
    else:
        iid = open_insights[0]["id"]
        info(f"  Using insight id={iid}")

        # Acknowledge
        r = requests.post(f"{BASE}/api/intelligence/insights/{iid}/acknowledge", headers=hdrs)
        check("POST acknowledge 200", r.status_code == 200, r.text[:120])
        check("Status is acknowledged", r.json().get("insight", {}).get("status") == "acknowledged")

        # Snooze from acknowledged
        import datetime, timezone as _tz
        snooze_dt = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)).isoformat()
        r = requests.post(
            f"{BASE}/api/intelligence/insights/{iid}/snooze",
            headers={**hdrs, "Content-Type": "application/json"},
            json={"snooze_until": snooze_dt},
        )
        check("POST snooze 200", r.status_code == 200, r.text[:120])
        check("Status is snoozed", r.json().get("insight", {}).get("status") == "snoozed")

        # Resolve
        r = requests.post(f"{BASE}/api/intelligence/insights/{iid}/resolve", headers=hdrs)
        check("POST resolve 200", r.status_code == 200, r.text[:120])
        check("Status is resolved", r.json().get("insight", {}).get("status") == "resolved")

        # Verify 404 on re-resolve (already resolved)
        r = requests.post(f"{BASE}/api/intelligence/insights/{iid}/resolve", headers=hdrs)
        check("Re-resolve returns 404", r.status_code == 404)

    # ── [7] Entity insights ───────────────────────────────────────────────────
    print("\n[7] Entity insights endpoint")
    r = requests.get(
        f"{BASE}/api/intelligence/insights/entity/tenant/fake-project-id",
        headers=hdrs,
    )
    check("GET entity insights 200", r.status_code == 200, r.text[:120])
    check("Returns insights list", "insights" in r.json())

    # ── [8] Auth guard ────────────────────────────────────────────────────────
    print("\n[8] Auth guard")
    r_noauth = requests.get(f"{BASE}/api/intelligence/insights")
    check("Unauthenticated access denied (401/403)", r_noauth.status_code in (401, 403))

    # ── [9] Department workspace filter ───────────────────────────────────────
    print("\n[9] Department workspace filter")

    DEPT_TYPES = {
        "support":     {"drift", "snapshot", "incident", "risk", "sla_risk"},
        "engineering": {"capacity", "waste", "anomaly", "cross_region"},
        "operations":  {"risk", "health", "sla_risk"},
    }

    for dept, expected_types in DEPT_TYPES.items():
        r = requests.get(
            f"{BASE}/api/intelligence/insights?department={dept}&page_size=200",
            headers=hdrs,
        )
        check(f"GET insights?department={dept} 200", r.status_code == 200, r.text[:120])
        items = r.json().get("insights", [])
        if items:
            returned_types = {i["type"].split("_")[0] for i in items}
            unexpected = returned_types - expected_types
            # Exact-type matches use full type name; map to prefix for flexible check
            full_unexpected = {
                i["type"] for i in items
                if not any(i["type"].startswith(et) for et in expected_types)
                and i["type"] not in expected_types
            }
            check(
                f"  {dept}: all returned types belong to workspace",
                len(full_unexpected) == 0,
                f"unexpected types: {full_unexpected}",
            )
        else:
            info(f"  {dept}: no insights currently; type-assertion skipped")

    # ?department= omitted → full feed (no type restriction)
    r_global = requests.get(f"{BASE}/api/intelligence/insights", headers=hdrs)
    r_dept   = requests.get(f"{BASE}/api/intelligence/insights?department=support", headers=hdrs)
    check("Global feed (no dept) >= support-scoped feed", r_global.json()["total"] >= r_dept.json()["total"])

    # risk type should appear in both support and operations workspaces (multi-dept routing)
    r_sup = requests.get(f"{BASE}/api/intelligence/insights?department=support&page_size=200",   headers=hdrs)
    r_ops = requests.get(f"{BASE}/api/intelligence/insights?department=operations&page_size=200", headers=hdrs)
    sup_types = {i["type"] for i in r_sup.json().get("insights", [])}
    ops_types = {i["type"] for i in r_ops.json().get("insights", [])}
    risk_types = {"risk", "risk_snapshot_gap", "risk_health_decline", "risk_unack_drift"}
    has_risk_in_sup = bool(sup_types & risk_types)
    has_risk_in_ops = bool(ops_types & risk_types)
    if has_risk_in_sup or has_risk_in_ops:
        # If risk insights exist, they must appear in BOTH workspaces
        check(
            "risk insights appear in both support and operations workspaces",
            has_risk_in_sup == has_risk_in_ops,
            f"sup has risk={has_risk_in_sup}, ops has risk={has_risk_in_ops}",
        )
    else:
        info("  No risk insights currently; multi-dept routing check skipped")

    # Department summary counts should be ≤ global summary total
    r_sum_global = requests.get(f"{BASE}/api/intelligence/insights/summary", headers=hdrs)
    r_sum_dept   = requests.get(f"{BASE}/api/intelligence/insights/summary?department=support", headers=hdrs)
    check("Dept summary total_open <= global total_open",
          r_sum_dept.json()["total_open"] <= r_sum_global.json()["total_open"])

    # Invalid department value → 422 Unprocessable Entity
    r_invalid = requests.get(f"{BASE}/api/intelligence/insights?department=invalid_dept", headers=hdrs)
    check("Invalid ?department= returns 422", r_invalid.status_code == 422)

    # ── Final ─────────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    if errors:
        print(f"FAILED checks ({len(errors)}): {errors}")
        pytest.fail(f"{len(errors)} check(s) failed: {errors}")
    else:
        print("All intelligence tests passed.")
