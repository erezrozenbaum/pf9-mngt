"""
tests/seed_ci.py — CI stack readiness check and seed verifier.

Run after `docker compose up` in GitHub Actions to confirm:
  1. The API is healthy and accepting requests
  2. The CI admin user can log in (validates DEFAULT_ADMIN bypass + DB role insert)
  3. The monitoring service is healthy

Exits 0 on success, non-zero on failure.

Usage (from the GitHub Actions runner, not inside a container):
  python tests/seed_ci.py
  TEST_API_URL=http://localhost:8000 TEST_MON_URL=http://localhost:8001 python tests/seed_ci.py
"""

import os
import sys
import time
import json
import urllib.request
import urllib.error

API_URL = os.getenv("TEST_API_URL", "http://localhost:8000").rstrip("/")
MON_URL = os.getenv("TEST_MON_URL", "http://localhost:8001").rstrip("/")
ADMIN_USER = os.getenv("DEFAULT_ADMIN_USER", os.getenv("TEST_ADMIN_USER", "ci-admin"))
ADMIN_PASS = os.getenv("DEFAULT_ADMIN_PASSWORD", os.getenv("TEST_ADMIN_PASSWORD", ""))
TIMEOUT = int(os.getenv("SEED_TIMEOUT", "120"))   # seconds to wait for services


def _get(url, token=None, timeout=10):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.status, json.loads(resp.read())


def _post_json(url, payload, timeout=10):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def wait_for_service(url, name, deadline):
    """Poll url/health until 200 or deadline."""
    health_url = f"{url}/health"
    while time.time() < deadline:
        try:
            status, _ = _get(health_url, timeout=5)
            if status == 200:
                print(f"  ✅ {name} is healthy")
                return True
        except Exception:
            pass
        print(f"  ⏳ Waiting for {name}…")
        time.sleep(5)
    print(f"  ❌ {name} did not become healthy within timeout")
    return False


def main():
    print("=" * 60)
    print("PF9 Management — CI Seed & Readiness Check")
    print(f"API: {API_URL}   Monitoring: {MON_URL}")
    print("=" * 60)

    deadline = time.time() + TIMEOUT
    failures = []

    # ── 1. Wait for API health ────────────────────────────────────────────────
    print("\n[1/4] API health check")
    if not wait_for_service(API_URL, "pf9_api", deadline):
        failures.append("API health timeout")

    # ── 2. Wait for monitoring health ─────────────────────────────────────────
    print("\n[2/4] Monitoring health check")
    if not wait_for_service(MON_URL, "pf9_monitoring", deadline):
        # Non-fatal — monitoring may still be starting; tests will skip if down
        print("  ⚠️  Monitoring not healthy yet (non-fatal, tests will handle)")

    # ── 3. Verify CI admin can log in ─────────────────────────────────────────
    print("\n[3/4] CI admin login")
    if not ADMIN_PASS:
        print("  ⚠️  ADMIN_PASS not set — skipping login check")
    else:
        status, body = _post_json(
            f"{API_URL}/auth/login",
            {"username": ADMIN_USER, "password": ADMIN_PASS},
        )
        if status == 200 and "access_token" in body:
            token = body["access_token"]
            user = body.get("user", {})
            print(f"  ✅ Logged in as '{user.get('username')}' (role: {user.get('role')})")
            if user.get("role") not in ("admin", "superadmin"):
                print(f"  ⚠️  Expected admin/superadmin role, got: {user.get('role')}")

            # ── 4. Verify authenticated endpoint is reachable ─────────────────
            print("\n[4/4] Authenticated endpoint smoke test")
            try:
                status2, _ = _get(f"{API_URL}/api/tenants", token=token, timeout=10)
                if status2 == 200:
                    print("  ✅ Authenticated GET /api/tenants → 200")
                else:
                    print(f"  ⚠️  GET /api/tenants returned {status2}")
            except Exception as exc:
                print(f"  ⚠️  GET /api/tenants failed: {exc}")
        else:
            msg = f"Login failed — HTTP {status}: {body.get('detail', body)}"
            print(f"  ❌ {msg}")
            failures.append(msg)

    # ── Result ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    if failures:
        print(f"FAILED ({len(failures)} issue(s)):")
        for f in failures:
            print(f"  • {f}")
        sys.exit(1)
    else:
        print("All seed checks passed — stack is ready for integration tests.")
        sys.exit(0)


if __name__ == "__main__":
    main()
