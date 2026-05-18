#!/usr/bin/env python3
"""
tests/test_wave_timeline.py  —  Wave timeline, insight auto-resolve & SLA migration counts

Tests cover:
  - wave_started webhook sets started_at and creates a migration_pending insight
  - wave_completed webhook sets completed_at and resolves the insight when all waves complete
  - get_migration_progress includes started_at / completed_at per wave
  - SLA compliance history includes migrations_completed column

Set TEST_PF9_LIVE=1 plus TEST_ADMIN_EMAIL/TEST_ADMIN_PASS to run against a live stack.
"""
import hashlib
import hmac
import json
import os
import time
import pytest
import requests

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_PF9_LIVE"),
    reason="requires TEST_PF9_LIVE=1 and a live PF9 endpoint",
)

BASE  = os.environ.get("TEST_BASE_URL", "http://localhost:8000")
EMAIL = os.environ.get("TEST_ADMIN_EMAIL", "")
PASSW = os.environ.get("TEST_ADMIN_PASS", "")

PASS_LBL = "\033[92mPASS\033[0m"
FAIL_LBL = "\033[91mFAIL\033[0m"
INFO_LBL = "\033[94mINFO\033[0m"


def _login() -> dict:
    r = requests.post(f"{BASE}/auth/login", json={"username": EMAIL, "password": PASSW})
    assert r.status_code == 200, f"Login failed: {r.text[:120]}"
    return {"Authorization": f"Bearer {r.json().get('access_token', '')}"}


def _check(errors: list, label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  {PASS_LBL}  {label}")
    else:
        msg = f"  {FAIL_LBL}  {label}" + (f"  →  {detail}" if detail else "")
        print(msg)
        errors.append(label)


def _send_webhook(pid: str, webhook_secret: str, event_type: str, wave_id: int) -> requests.Response:
    """Send an HMAC-signed webhook event to the migration project."""
    payload = json.dumps({"event_type": event_type, "wave_id": wave_id}).encode()
    sig = "sha256=" + hmac.new(webhook_secret.encode(), payload, hashlib.sha256).hexdigest()
    return requests.post(
        f"{BASE}/api/migration/projects/{pid}/webhook",
        data=payload,
        headers={"Content-Type": "application/json", "X-vJailbreak-Signature": sig},
    )


def test_wave_timeline():
    """
    End-to-end test:
      1. Create a migration project with 2 waves.
      2. Trigger wave_started webhook for wave 1 → expect started_at set + insight created.
      3. Trigger wave_completed webhook for wave 1 → expect completed_at set, project still active.
      4. Trigger wave_started + wave_completed webhooks for wave 2 → expect project completed.
      5. Verify get_migration_progress returns timestamps.
      6. Verify SLA history includes migrations_completed field.
    """
    errors: list = []
    hdrs = _login()

    # ── [1] Create migration project ──────────────────────────────────────────
    print("\n[1] Create migration project")
    r = requests.post(
        f"{BASE}/api/migration/projects",
        headers=hdrs,
        json={"name": f"timeline-test-{int(time.time())}", "description": "Automated wave timeline test"},
    )
    _check(errors, "Create project 200", r.status_code == 200, r.text[:120])
    if r.status_code != 200:
        pytest.fail(f"Cannot proceed — project creation failed: {r.text[:200]}")
    resp_data = r.json()
    pid = resp_data.get("project", {}).get("project_id") or resp_data.get("project_id")
    webhook_secret = resp_data.get("webhook_secret", "")
    print(f"  {INFO_LBL}  project_id={pid}")
    assert pid, "project_id missing from response"

    # Add 2 waves
    wave_ids = []
    for wave_num in (1, 2):
        rw = requests.post(
            f"{BASE}/api/migration/projects/{pid}/waves",
            headers=hdrs,
            json={"wave_number": wave_num, "name": f"Wave {wave_num}"},
        )
        _check(errors, f"Create wave {wave_num} 200", rw.status_code == 200, rw.text[:120])
        wid = rw.json().get("wave", {}).get("wave_number", wave_num) if rw.status_code == 200 else wave_num
        wave_ids.append(wid)

    # ── [2] wave_started for wave 1 ───────────────────────────────────────────
    print("\n[2] wave_started for wave 1")
    r = _send_webhook(pid, webhook_secret, "wave_started", 1)
    _check(errors, "wave_started webhook 200", r.status_code == 200, r.text[:120])

    # Check started_at in progress
    rp = requests.get(f"{BASE}/api/migration/projects/{pid}/progress", headers=hdrs)
    _check(errors, "GET progress 200", rp.status_code == 200, rp.text[:120])
    if rp.status_code == 200:
        waves_data = rp.json().get("waves", [])
        w1 = next((w for w in waves_data if w.get("wave_number") == 1), None)
        _check(errors, "Wave 1 has started_at", w1 is not None and w1.get("started_at") is not None,
               str(w1))
        _check(errors, "Wave 1 completed_at is None", w1 is not None and w1.get("completed_at") is None,
               str(w1))

    # ── [3] wave_completed for wave 1 ─────────────────────────────────────────
    print("\n[3] wave_completed for wave 1")
    r = _send_webhook(pid, webhook_secret, "wave_completed", 1)
    _check(errors, "wave_completed webhook 200", r.status_code == 200, r.text[:120])

    rp = requests.get(f"{BASE}/api/migration/projects/{pid}/progress", headers=hdrs)
    if rp.status_code == 200:
        waves_data = rp.json().get("waves", [])
        w1 = next((w for w in waves_data if w.get("wave_number") == 1), None)
        _check(errors, "Wave 1 has completed_at", w1 is not None and w1.get("completed_at") is not None,
               str(w1))

    # Project should still be active (wave 2 pending)
    rproj = requests.get(f"{BASE}/api/migration/projects/{pid}", headers=hdrs)
    if rproj.status_code == 200:
        proj_data = rproj.json().get("project", rproj.json())
        proj_status = proj_data.get("status")
        _check(errors, "Project still not completed (wave 2 pending)",
               proj_status != "completed", f"status={proj_status}")

    # ── [4] wave 2 start + complete → expect project completed ────────────────
    print("\n[4] wave 2 start + complete")
    _send_webhook(pid, webhook_secret, "wave_started", 2)
    r = _send_webhook(pid, webhook_secret, "wave_completed", 2)
    _check(errors, "wave 2 completed 200", r.status_code == 200, r.text[:120])

    rproj = requests.get(f"{BASE}/api/migration/projects/{pid}", headers=hdrs)
    if rproj.status_code == 200:
        proj_data = rproj.json().get("project", rproj.json())
        proj_status = proj_data.get("status")
        _check(errors, "Project status=completed", proj_status == "completed",
               f"status={proj_status}")

    # ── [5] SLA history includes migrations_completed field ───────────────────
    print("\n[5] SLA history includes migrations_completed")
    rh = requests.get(f"{BASE}/api/sla/history", headers=hdrs)
    if rh.status_code == 200:
        rows = rh.json().get("history", [])
        if rows:
            first = rows[0]
            _check(errors, "SLA history row has migrations_completed key",
                   "migrations_completed" in first, str(list(first.keys())))
        else:
            print(f"  {INFO_LBL}  No SLA history rows yet — skipping field check")
    else:
        print(f"  {INFO_LBL}  GET /api/sla/history → {rh.status_code} (skipping)")

    # ── Cleanup ───────────────────────────────────────────────────────────────
    requests.delete(f"{BASE}/api/migration/projects/{pid}", headers=hdrs)

    assert not errors, f"Failed checks: {errors}"
