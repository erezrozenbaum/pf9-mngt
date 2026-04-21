#!/usr/bin/env python3
"""
Phase 4 Operational Intelligence tests — v1.90.0
MSP & Business Value Layer:
  - Labor Rates CRUD
  - QBR Preview + PDF generation
  - PSA Webhook CRUD + test-fire + security (encrypted auth_header)
  - Revenue Leakage dept routing
  - SLA PDF + QBR PDF generation (unit)
  - Security boundary checks

Set TEST_PF9_LIVE=1 plus TEST_ADMIN_EMAIL/TEST_ADMIN_PASS to run against a live stack.
"""
import os
import sys
import json

import pytest
import requests

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_PF9_LIVE"),
    reason="requires TEST_PF9_LIVE=1 and a live PF9 endpoint",
)

# ---------------------------------------------------------------------------
# Unit tests — no live stack required
# ---------------------------------------------------------------------------

def test_leakage_dept_routing():
    """Leakage insight types must route to operations + general departments."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
    from intelligence_utils import map_insight_to_departments
    depts = map_insight_to_departments("leakage_overconsumption")
    assert "operations" in depts, f"expected 'operations' in {depts}"
    assert "general" in depts, f"expected 'general' in {depts}"
    depts2 = map_insight_to_departments("leakage_ghost")
    assert "operations" in depts2


def test_generate_sla_report_pdf():
    """generate_sla_report returns a valid PDF."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
    try:
        from export_reports import generate_sla_report
    except ImportError:
        pytest.skip("export_reports not importable in this env")
    tenant = {
        "project_id":   "t-001",
        "project_name": "TestCo",
        "sla_tier":     "gold",
        "support_email": "support@test.co",
        "sla_commitments": {},
        "sla_compliance": {},
    }
    history = [
        {
            "month": "2025-01-01",
            "uptime_actual": 99.9, "uptime_target": 99.5,
            "mttr_actual": 2.0, "mttr_target": 4.0,
            "incidents": 1, "incidents_limit": 3,
            "tickets_resolved": 10, "tickets_target": 12,
            "csat": 4.2, "csat_target": 4.0,
            "overall_status": "met",
        }
    ]
    pdf = generate_sla_report("t-001", tenant, history, "2025-01", "2025-01")
    assert isinstance(pdf, bytes)
    assert pdf[:4] == b"%PDF", "output is not a PDF"


def test_generate_qbr_pdf():
    """generate_qbr_pdf returns a valid PDF."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
    try:
        from export_reports import generate_qbr_pdf
    except ImportError:
        pytest.skip("export_reports not importable in this env")
    qbr_data = {
        "tenant_id":          "t-001",
        "tenant_name":        "TestCo",
        "from_date":          "2025-01-01",
        "to_date":            "2025-03-31",
        "total_hours_saved":  12.5,
        "total_cost_avoided": 1875.0,
        "incidents_prevented": 5,
        "interventions":      [
            {
                "insight_type": "capacity",
                "count":        3,
                "hours_saved":  1.5,
                "rate":         150.0,
                "total_cost":   675.0,
            }
        ],
        "open_items": [],
        "health_trend": [],
    }
    pdf = generate_qbr_pdf(qbr_data, ["cover", "executive_summary", "interventions", "methodology"])
    assert isinstance(pdf, bytes)
    assert pdf[:4] == b"%PDF", "output is not a PDF"


# ---------------------------------------------------------------------------
# Live stack tests
# ---------------------------------------------------------------------------

def test_phase4_live():  # noqa: C901
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
            msg = f"  {FAIL}  {label}" + (f"  → {detail}" if detail else "")
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

    # ── [1] Labor Rates ───────────────────────────────────────────────────────
    print("\n[1] Labor Rates")
    r = requests.get(f"{BASE}/api/intelligence/qbr/labor-rates", headers=hdrs)
    check("GET labor-rates 200", r.status_code == 200, r.text[:120])
    if r.status_code == 200:
        body = r.json()
        check("Response has 'rates' list", "rates" in body)
        rates = body.get("rates", [])
        check("At least 8 default rates", len(rates) >= 8, f"got {len(rates)}")
        leakage_rate = next((rt for rt in rates if rt["insight_type"] == "leakage"), None)
        check("leakage rate exists", leakage_rate is not None)
        info(f"leakage rate: {leakage_rate}")

    # ── [2] Update a labor rate ───────────────────────────────────────────────
    print("\n[2] Update labor rate (capacity)")
    r = requests.put(
        f"{BASE}/api/intelligence/qbr/labor-rates/capacity",
        headers={**hdrs, "Content-Type": "application/json"},
        data=json.dumps({"hours_saved": 2.0, "rate_per_hour": 160.0, "description": "Updated by test"}),
    )
    check("PUT labor-rates/capacity 200", r.status_code == 200, r.text[:120])
    if r.status_code == 200:
        upd = r.json()
        check("Updated hours_saved == 2.0", float(upd.get("hours_saved", 0)) == 2.0)
        check("Updated rate_per_hour == 160.0", float(upd.get("rate_per_hour", 0)) == 160.0)

    # ── [3] QBR preview (no valid tenant → 404) ───────────────────────────────
    print("\n[3] QBR preview — invalid tenant")
    r = requests.get(
        f"{BASE}/api/intelligence/qbr/preview/nonexistent-tenant-000",
        headers=hdrs,
    )
    check("GET qbr/preview/nonexistent → 404", r.status_code == 404, r.text[:120])

    # ── [4] QBR preview — first real tenant ───────────────────────────────────
    print("\n[4] QBR preview — real tenant")
    r2 = requests.get(f"{BASE}/api/intelligence/insights", headers=hdrs)
    tenant_id: str | None = None
    if r2.status_code == 200:
        insights = r2.json().get("insights", [])
        if insights:
            tenant_id = insights[0].get("entity_id")
    if tenant_id is None:
        # Try to find first tenant from SLA list
        r3 = requests.get(f"{BASE}/api/sla/tenants", headers=hdrs)
        if r3.status_code == 200:
            ts = r3.json().get("tenants", [])
            if ts:
                tenant_id = ts[0].get("project_id")
    if tenant_id:
        r = requests.get(f"{BASE}/api/intelligence/qbr/preview/{tenant_id}", headers=hdrs)
        check(f"GET qbr/preview/{tenant_id} 200", r.status_code == 200, r.text[:120])
        if r.status_code == 200:
            preview = r.json()
            check("Preview has 'tenant_id'", "tenant_id" in preview)
            check("Preview has 'total_cost_avoided'", "total_cost_avoided" in preview)
            check("Preview has 'interventions'", "interventions" in preview)
            info(f"total_cost_avoided: ${preview.get('total_cost_avoided', 0):.2f}")
    else:
        info("No tenants found — skipping QBR preview test")

    # ── [5] PSA Config CRUD ───────────────────────────────────────────────────
    print("\n[5] PSA Config CRUD")
    # Create
    psa_payload = {
        "psa_name":     "Test Webhook",
        "webhook_url":  "https://httpbin.org/post",
        "auth_header":  "Bearer test-token-phase4",
        "min_severity": "high",
        "insight_types": [],
        "region_ids":   [],
        "enabled":      True,
    }
    r = requests.post(
        f"{BASE}/api/psa/configs",
        headers={**hdrs, "Content-Type": "application/json"},
        data=json.dumps(psa_payload),
    )
    check("POST /psa/configs 201", r.status_code == 201, r.text[:120])
    new_id: int | None = None
    if r.status_code == 201:
        new_id = r.json().get("id")
        check("POST response has 'id'", new_id is not None)

        # List
        r = requests.get(f"{BASE}/api/psa/configs", headers=hdrs)
        check("GET /psa/configs 200", r.status_code == 200, r.text[:120])
        if r.status_code == 200:
            configs_body = r.json()
            check("Response has 'configs'", "configs" in configs_body)
            found = next((c for c in configs_body.get("configs", []) if c.get("id") == new_id), None)
            check("New config in list", found is not None)
            # Security: auth_header must NOT appear in plaintext
            if found:
                auth_val = found.get("auth_header", "")
                check(
                    "auth_header not in plaintext (security)",
                    "test-token-phase4" not in (auth_val or ""),
                    f"auth_header was: {auth_val}",
                )

        # Update
        r = requests.put(
            f"{BASE}/api/psa/configs/{new_id}",
            headers={**hdrs, "Content-Type": "application/json"},
            data=json.dumps({
                **psa_payload,
                "psa_name":    "Test Webhook Updated",
                "min_severity": "critical",
            }),
        )
        check("PUT /psa/configs/{id} 200", r.status_code == 200, r.text[:120])
        if r.status_code == 200:
            upd = r.json()
            check("Updated min_severity == critical", upd.get("min_severity") == "critical")
            check("Updated psa_name", upd.get("psa_name") == "Test Webhook Updated")

        # Test-fire (httpbin returns 200)
        r = requests.post(f"{BASE}/api/psa/configs/{new_id}/test-fire", headers=hdrs)
        check("POST /psa/configs/{id}/test-fire 200", r.status_code == 200, r.text[:120])
        if r.status_code == 200:
            tf = r.json()
            check("test-fire success == True", tf.get("success") is True, json.dumps(tf))

        # Delete
        r = requests.delete(f"{BASE}/api/psa/configs/{new_id}", headers=hdrs)
        check("DELETE /psa/configs/{id} 200", r.status_code == 200, r.text[:120])
        # Verify deleted
        r = requests.get(f"{BASE}/api/psa/configs", headers=hdrs)
        if r.status_code == 200:
            still_there = any(c.get("id") == new_id for c in r.json().get("configs", []))
            check("Config removed from list after delete", not still_there)

    # ── [6] PSA Config — invalid min_severity rejected ────────────────────────
    print("\n[6] PSA Config — security validation")
    r = requests.post(
        f"{BASE}/api/psa/configs",
        headers={**hdrs, "Content-Type": "application/json"},
        data=json.dumps({
            **psa_payload,
            "min_severity": "banana",
        }),
    )
    check("Invalid min_severity → 422", r.status_code == 422, r.text[:120])

    # ── [7] PSA Config — non-https URL rejected ───────────────────────────────
    r = requests.post(
        f"{BASE}/api/psa/configs",
        headers={**hdrs, "Content-Type": "application/json"},
        data=json.dumps({
            **psa_payload,
            "webhook_url": "ftp://notallowed.com/hook",
        }),
    )
    check("Non-http(s) webhook_url → 422", r.status_code == 422, r.text[:120])

    # ── [8] PSA test-fire on missing config ───────────────────────────────────
    print("\n[8] PSA test-fire on missing config")
    r = requests.post(f"{BASE}/api/psa/configs/99999999/test-fire", headers=hdrs)
    check("test-fire nonexistent → 404", r.status_code == 404, r.text[:120])

    # ── [9] QBR generate PDF (if tenant available) ────────────────────────────
    print("\n[9] QBR generate PDF")
    if tenant_id:
        r = requests.post(
            f"{BASE}/api/intelligence/qbr/generate/{tenant_id}",
            headers={**hdrs, "Content-Type": "application/json"},
            data=json.dumps({
                "tenant_id": tenant_id,
                "include_sections": ["cover", "executive_summary", "interventions", "methodology"],
            }),
        )
        check("POST qbr/generate/{tenant_id} 200", r.status_code == 200, r.text[:120])
        if r.status_code == 200:
            ct = r.headers.get("content-type", "")
            check("Content-Type is PDF", "pdf" in ct, ct)
            check("Response body is non-empty", len(r.content) > 100)
            check("Response body starts with %PDF", r.content[:4] == b"%PDF", r.content[:20].hex())
    else:
        info("No tenant_id available — skipping QBR PDF generation test")

    # ── Done ──────────────────────────────────────────────────────────────────
    print()
    if errors:
        pytest.fail(f"{len(errors)} assertion(s) failed:\n" + "\n".join(f"  - {e}" for e in errors))
