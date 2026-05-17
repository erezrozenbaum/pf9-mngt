"""Quick live test for webhook HMAC endpoint."""
import hmac
import hashlib
import urllib.request
import urllib.error
import json

BASE = "http://localhost:8000"
PROJECT = "test-webhook-proj"
SECRET = b"test-secret-for-webhook-test-abc123"


def call(body_bytes, sig_header=None):
    headers = {"Content-Type": "application/json"}
    if sig_header is not None:
        headers["X-vJailbreak-Signature"] = sig_header
    req = urllib.request.Request(
        f"{BASE}/api/migration/projects/{PROJECT}/webhook",
        data=body_bytes,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


body = json.dumps({"event_type": "vm_migrated", "vm_id": "vm-test-001", "wave_id": 1}).encode()
good_sig = "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()

print("=== Test 1: No signature header → expect 401 (handler rejects missing sig) ===")
code, resp = call(body)
print(f"  {code}: {resp}")
assert code == 401, f"Expected 401, got {code}"
assert "signature" in resp.get("detail", "").lower(), f"Unexpected detail: {resp}"

print("=== Test 2: Wrong signature → expect 401 ===")
code, resp = call(body, "sha256=badhashbadhash")
print(f"  {code}: {resp}")
assert code == 401, f"Expected 401, got {code}"

print("=== Test 3: Valid HMAC signature → expect 200 ===")
code, resp = call(body, good_sig)
print(f"  {code}: {resp}")
assert code == 200, f"Expected 200, got {code}"
assert resp.get("status") == "accepted", f"Unexpected body: {resp}"

print()
print("All webhook tests PASSED.")
