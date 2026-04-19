#!/usr/bin/env python3
"""
SLA Compliance Tracking test suite  —  v1.85.0
Set TEST_PF9_LIVE=1 plus TEST_ADMIN_EMAIL/TEST_ADMIN_PASS to run against a live stack.
"""
import os

import pytest
import requests

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_PF9_LIVE"),
    reason="requires TEST_PF9_LIVE=1 and a live PF9 endpoint",
)


def test_sla_compliance():  # noqa: C901
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
    token  = r.json().get("token", "")
    hdrs   = {"Authorization": f"Bearer {token}"}

    # ── [1] SLA tier templates ────────────────────────────────────────────────
    print("\n[1] SLA tier templates")
    r = requests.get(f"{BASE}/api/sla/tiers", headers=hdrs)
    check("GET /api/sla/tiers 200", r.status_code == 200, r.text[:120])
    tiers = r.json().get("tiers", [])
    check("Tiers list not empty", len(tiers) > 0)
    tier_names = [t["tier"] for t in tiers]
    check("Bronze tier present", "bronze" in tier_names)
    check("Silver tier present", "silver" in tier_names)
    check("Gold tier present",   "gold"   in tier_names)

    # ── [2] SLA compliance summary ────────────────────────────────────────────
    print("\n[2] SLA compliance summary")
    r = requests.get(f"{BASE}/api/sla/compliance/summary", headers=hdrs)
    check("GET /api/sla/compliance/summary 200", r.status_code == 200, r.text[:120])
    summary = r.json().get("projects", [])
    check("Summary returns a list", isinstance(summary, list))
    if summary:
        first = summary[0]
        check("Row has project_id",     "project_id"     in first)
        check("Row has overall_status", "overall_status" in first)
        info(f"  Sample row: {list(first.keys())}")

    # ── [3] Unauthenticated access denied ─────────────────────────────────────
    print("\n[3] Auth guard")
    r_noauth = requests.get(f"{BASE}/api/sla/tiers")
    check("Unauthenticated /api/sla/tiers denied (401/403)",
          r_noauth.status_code in (401, 403))

    # ── [4] Commitment on nonexistent tenant returns 404 ─────────────────────
    print("\n[4] Commitment 404 for unknown tenant")
    r = requests.get(f"{BASE}/api/sla/commitments/nonexistent-tenant-id-xyz", headers=hdrs)
    check("GET commitment for unknown tenant returns 404", r.status_code == 404)

    # ── Final ─────────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    if errors:
        print(f"FAILED checks ({len(errors)}): {errors}")
        pytest.fail(f"{len(errors)} check(s) failed: {errors}")
    else:
        print("All SLA compliance tests passed.")
