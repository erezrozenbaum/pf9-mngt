"""
One-time setup script: create provisionsrv@ccc.co.il in PCD Keystone.
Run inside the API container:
  docker exec pf9_api python3 /app/setup_provision_user.py

Or from the host with the venv (requires PF9_* env vars exported):
  python setup_provision_user.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from pf9_control import Pf9Client
from cryptography.fernet import Fernet


def main():
    key = os.environ.get("PROVISION_PASSWORD_KEY", "")
    enc = os.environ.get("PROVISION_USER_PASSWORD_ENCRYPTED", "")
    email = os.environ.get("PROVISION_SERVICE_USER_EMAIL", "")
    domain = os.environ.get("PROVISION_SERVICE_USER_DOMAIN", "Default")

    if not key or not enc or not email:
        print("ERROR: PROVISION_PASSWORD_KEY, PROVISION_USER_PASSWORD_ENCRYPTED, "
              "and PROVISION_SERVICE_USER_EMAIL must all be set in .env")
        sys.exit(1)

    password = Fernet(key.encode()).decrypt(enc.encode()).decode()
    print(f"Setting up provisionsrv user: {email}")

    client = Pf9Client()
    client.authenticate()

    # Resolve domain ID
    r = client.session.get(
        f"{client.keystone_endpoint}/domains",
        headers={"X-Auth-Token": client.token},
        params={"name": domain},
    )
    r.raise_for_status()
    domains = r.json().get("domains", [])
    if not domains:
        print(f"ERROR: Keystone domain '{domain}' not found")
        sys.exit(1)
    domain_id = domains[0]["id"]
    print(f"  Domain '{domain}' → {domain_id}")

    # Check if user already exists
    r2 = client.session.get(
        f"{client.keystone_endpoint}/users",
        headers={"X-Auth-Token": client.token},
        params={"name": email},
    )
    r2.raise_for_status()
    existing = r2.json().get("users", [])
    if existing:
        uid = existing[0]["id"]
        print(f"  User already exists → {uid}")
        print("DONE (no-op)")
        return

    # Create user — service account, no password expiry
    body = {
        "user": {
            "name": email,
            "password": password,
            "domain_id": domain_id,
            "email": email,
            "description": "VM Provisioning service account (system) — do not delete",
            "enabled": True,
            "options": {"ignore_password_expiry": True},
        }
    }
    r3 = client.session.post(
        f"{client.keystone_endpoint}/users",
        headers={"X-Auth-Token": client.token, "Content-Type": "application/json"},
        json=body,
    )
    if not r3.ok:
        print(f"ERROR creating user: {r3.status_code} {r3.text}")
        sys.exit(1)

    user = r3.json()["user"]
    print(f"  Created provisionsrv → {user['id']}")
    print("DONE")


if __name__ == "__main__":
    main()
