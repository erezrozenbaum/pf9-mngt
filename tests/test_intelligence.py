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

    # ── [10] Bulk-acknowledge ─────────────────────────────────────────────────
    print("\n[10] Bulk-acknowledge")
    r = requests.post(
        f"{BASE}/api/intelligence/insights/bulk-acknowledge",
        headers={**hdrs, "Content-Type": "application/json"},
        json={"severity": "low"},
    )
    check("POST bulk-acknowledge 200", r.status_code == 200, r.text[:120])
    body = r.json()
    check("Response has 'acknowledged' count", "acknowledged" in body)
    check("Acknowledged count is int >= 0", isinstance(body.get("acknowledged"), int) and body["acknowledged"] >= 0)
    info(f"  Bulk-acknowledged {body.get('acknowledged', '?')} low-severity insights")

    # Verify filter applies: bulk-ack with unknown type should ack zero
    r_zero = requests.post(
        f"{BASE}/api/intelligence/insights/bulk-acknowledge",
        headers={**hdrs, "Content-Type": "application/json"},
        json={"type": "__nonexistent_type_xyz__"},
    )
    check("Bulk-acknowledge unknown type acks 0", r_zero.json().get("acknowledged", -1) == 0)

    # ── [11] Bulk-resolve ────────────────────────────────────────────────────
    print("\n[11] Bulk-resolve")
    r = requests.post(
        f"{BASE}/api/intelligence/insights/bulk-resolve",
        headers={**hdrs, "Content-Type": "application/json"},
        json={"type": "waste_idle_vm"},
    )
    check("POST bulk-resolve 200", r.status_code == 200, r.text[:120])
    body = r.json()
    check("Response has 'resolved' count", "resolved" in body)
    check("Resolved count is int >= 0", isinstance(body.get("resolved"), int) and body["resolved"] >= 0)
    info(f"  Bulk-resolved {body.get('resolved', '?')} waste_idle_vm insights")

    # Verify empty body still returns 200 (resolves all open)
    r_all = requests.post(
        f"{BASE}/api/intelligence/insights/bulk-resolve",
        headers={**hdrs, "Content-Type": "application/json"},
        json={},
    )
    check("POST bulk-resolve empty body 200", r_all.status_code == 200)

    # ── [12] Recommendations ─────────────────────────────────────────────────
    print("\n[12] Recommendations")
    # Re-fetch any open insight that could have recommendations
    r = requests.get(f"{BASE}/api/intelligence/insights?status=open&page_size=10", headers=hdrs)
    open_items = r.json().get("insights", [])
    if not open_items:
        info("  No open insights; creating a dummy check on id=1")
        # GET on a non-existent insight's recs should still return 200 with empty list or 404
        r_recs = requests.get(f"{BASE}/api/intelligence/insights/1/recommendations", headers=hdrs)
        check("GET /insights/1/recommendations returns 200 or 404",
              r_recs.status_code in (200, 404))
    else:
        iid = open_items[0]["id"]
        r_recs = requests.get(f"{BASE}/api/intelligence/insights/{iid}/recommendations", headers=hdrs)
        check(f"GET /insights/{iid}/recommendations 200", r_recs.status_code == 200, r_recs.text[:120])
        check("Response has 'recommendations' list", "recommendations" in r_recs.json())
        recs = r_recs.json()["recommendations"]
        info(f"  Found {len(recs)} recommendation(s) for insight {iid}")
        if recs:
            rec = recs[0]
            check("Rec has id",               "id" in rec)
            check("Rec has action_type",      "action_type" in rec)
            check("Rec has action_payload",   "action_payload" in rec)
            check("Rec has status",           "status" in rec)
            check("Rec status is valid",
                  rec.get("status") in ("pending", "executed", "dismissed"))

    # ── [13] Dismiss recommendation ───────────────────────────────────────────
    print("\n[13] Dismiss recommendation")
    # Find an insight with pending recommendations to dismiss
    r = requests.get(f"{BASE}/api/intelligence/insights?status=open&page_size=50", headers=hdrs)
    candidate_iid: int | None = None
    candidate_rid: int | None = None
    for item in r.json().get("insights", []):
        r_recs = requests.get(f"{BASE}/api/intelligence/insights/{item['id']}/recommendations", headers=hdrs)
        if r_recs.status_code == 200:
            pending = [rx for rx in r_recs.json().get("recommendations", []) if rx["status"] == "pending"]
            if pending:
                candidate_iid = item["id"]
                candidate_rid = pending[0]["id"]
                break
    if candidate_iid is None:
        info("  No pending recommendations found; dismiss test skipped")
    else:
        info(f"  Dismissing rec {candidate_rid} on insight {candidate_iid}")
        r_dis = requests.post(
            f"{BASE}/api/intelligence/insights/{candidate_iid}/recommendations/{candidate_rid}/dismiss",
            headers=hdrs,
        )
        check("POST dismiss 200", r_dis.status_code == 200, r_dis.text[:120])
        check("Response has dismissed=True", r_dis.json().get("dismissed") is True)

        # Idempotency — second dismiss returns 404 (already dismissed)
        r_dis2 = requests.post(
            f"{BASE}/api/intelligence/insights/{candidate_iid}/recommendations/{candidate_rid}/dismiss",
            headers=hdrs,
        )
        check("Re-dismiss returns 404", r_dis2.status_code == 404)

    # ── [14] Capacity Forecast endpoint ───────────────────────────────────────
    print("\n[14] Capacity Forecast endpoint")
    r = requests.get(f"{BASE}/api/intelligence/forecast", headers=hdrs)
    check("GET /api/intelligence/forecast 200", r.status_code == 200, r.text[:120])
    body = r.json()
    check("Response has 'forecasts' list", "forecasts" in body)
    forecasts = body.get("forecasts", [])
    info(f"  {len(forecasts)} project forecast(s) returned")
    if forecasts:
        f0 = forecasts[0]
        check("Forecast has project_id",    "project_id"   in f0)
        check("Forecast has project_name",  "project_name" in f0)
        check("Forecast has resources",     "resources"    in f0)
        resources = f0.get("resources", {})
        if resources:
            resource_key = next(iter(resources))
            r0 = resources[resource_key]
            check(f"Resource '{resource_key}' has used",    "used"    in r0)
            check(f"Resource '{resource_key}' has quota",   "quota"   in r0)
            check(f"Resource '{resource_key}' has days_to_90", "days_to_90" in r0)

    # ── [15] Region Comparison endpoint ───────────────────────────────────────
    print("\n[15] Region Comparison endpoint")
    r = requests.get(f"{BASE}/api/intelligence/regions", headers=hdrs)
    check("GET /api/intelligence/regions 200", r.status_code == 200, r.text[:120])
    body = r.json()
    check("Response has 'regions' list", "regions" in body)
    regions = body.get("regions", [])
    info(f"  {len(regions)} region(s) returned")
    if regions:
        reg = regions[0]
        check("Region has region_id",          "region_id"          in reg)
        check("Region has hypervisors",        "hypervisors"        in reg)
        check("Region has vcpu_utilization",   "vcpu_utilization"   in reg)
        check("Region has open_critical",      "open_critical"      in reg)
        check("Region has capacity_runway_days", "capacity_runway_days" in reg)

    # ── Final ─────────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    if errors:
        print(f"FAILED checks ({len(errors)}): {errors}")
        pytest.fail(f"{len(errors)} check(s) failed: {errors}")
    else:
        print("All intelligence tests passed.")
