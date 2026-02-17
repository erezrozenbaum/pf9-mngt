"""
MFA (Multi-Factor Authentication) API Routes
=============================================
Endpoints for TOTP-based two-factor authentication using Google Authenticator
compatible apps.

Flow:
  1. User calls POST /auth/mfa/setup → receives QR code + secret
  2. User scans QR in Google Authenticator and submits the first code
     via POST /auth/mfa/verify-setup → MFA is now enabled
  3. On next login, after LDAP auth succeeds the API returns
     mfa_required=true + mfa_token (short-lived).  The client then
     calls POST /auth/mfa/verify with the TOTP code to get the real JWT.
  4. User can disable MFA via POST /auth/mfa/disable

RBAC:
  - Any authenticated user can manage their own MFA.
  - admin+ can view MFA status list for all users.
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional, List

import pyotp
import qrcode

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from psycopg2.extras import RealDictCursor

from auth import (
    get_current_user,
    require_authentication,
    require_permission,
    User,
    JWT_SECRET_KEY,
    JWT_ALGORITHM,
)
from db_pool import get_connection

logger = logging.getLogger("pf9.mfa")

router = APIRouter(prefix="/auth/mfa", tags=["mfa"])

MFA_ISSUER = "PF9 Management"
MFA_TOKEN_EXPIRE_MINUTES = 5  # Short-lived token for MFA challenge step
BACKUP_CODE_COUNT = 8


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class MFASetupResponse(BaseModel):
    secret: str
    qr_code_base64: str
    otpauth_url: str

class MFAVerifyRequest(BaseModel):
    code: str

class MFAStatusResponse(BaseModel):
    enabled: bool
    created_at: Optional[str] = None

class MFAUserListItem(BaseModel):
    username: str
    mfa_enabled: bool
    created_at: Optional[str] = None

class MFADisableRequest(BaseModel):
    code: str  # require current TOTP code to disable

class MFABackupCodesResponse(BaseModel):
    backup_codes: List[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_backup_codes(count: int = BACKUP_CODE_COUNT) -> tuple[list[str], list[str]]:
    """Generate plaintext + hashed backup codes."""
    plain = [secrets.token_hex(4).upper() for _ in range(count)]  # e.g. "A1B2C3D4"
    hashed = [hashlib.sha256(c.encode()).hexdigest() for c in plain]
    return plain, hashed


def _verify_backup_code(code: str, stored_hashes: list[str]) -> int:
    """Return index of matching backup code or -1."""
    h = hashlib.sha256(code.strip().upper().encode()).hexdigest()
    for i, stored in enumerate(stored_hashes):
        if h == stored:
            return i
    return -1


def _get_mfa_record(username: str) -> Optional[dict]:
    """Fetch MFA record for a user."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM user_mfa WHERE username = %s", (username,))
            return cur.fetchone()


def _generate_qr_base64(otpauth_url: str) -> str:
    """Generate a QR code PNG as a base64-encoded data URI."""
    img = qrcode.make(otpauth_url, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


# ---------------------------------------------------------------------------
# POST /auth/mfa/setup – Begin MFA enrollment
# ---------------------------------------------------------------------------
@router.post("/setup", response_model=MFASetupResponse)
async def mfa_setup(current_user: User = Depends(require_authentication)):
    """Generate TOTP secret and QR code for the current user.
    Can be called again to re-enroll (replaces existing unenabled record)."""
    username = current_user.username

    # Check if already enabled
    existing = _get_mfa_record(username)
    if existing and existing["is_enabled"]:
        raise HTTPException(
            status_code=400,
            detail="MFA is already enabled. Disable it first to re-enroll.",
        )

    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    otpauth_url = totp.provisioning_uri(name=username, issuer_name=MFA_ISSUER)
    qr_b64 = _generate_qr_base64(otpauth_url)

    # Upsert (replace any previous un-verified enrollment)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_mfa (username, totp_secret, is_enabled, updated_at)
                VALUES (%s, %s, false, now())
                ON CONFLICT (username) DO UPDATE
                    SET totp_secret = EXCLUDED.totp_secret,
                        is_enabled = false,
                        backup_codes = NULL,
                        updated_at = now()
                """,
                (username, secret),
            )
        conn.commit()

    logger.info("MFA setup initiated for %s", username)
    return MFASetupResponse(secret=secret, qr_code_base64=qr_b64, otpauth_url=otpauth_url)


# ---------------------------------------------------------------------------
# POST /auth/mfa/verify-setup – Confirm enrollment with first TOTP code
# ---------------------------------------------------------------------------
@router.post("/verify-setup", response_model=MFABackupCodesResponse)
async def mfa_verify_setup(
    body: MFAVerifyRequest,
    current_user: User = Depends(require_authentication),
):
    """Verify the first TOTP code to confirm MFA enrollment.
    Returns one-time backup codes."""
    username = current_user.username
    record = _get_mfa_record(username)

    if not record:
        raise HTTPException(status_code=400, detail="Call /auth/mfa/setup first")
    if record["is_enabled"]:
        raise HTTPException(status_code=400, detail="MFA is already enabled")

    totp = pyotp.TOTP(record["totp_secret"])
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")

    # Generate backup codes
    plain_codes, hashed_codes = _generate_backup_codes()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE user_mfa
                SET is_enabled = true, backup_codes = %s, updated_at = now()
                WHERE username = %s
                """,
                (hashed_codes, username),
            )
        conn.commit()

    logger.info("MFA enabled for %s", username)
    return MFABackupCodesResponse(backup_codes=plain_codes)


# ---------------------------------------------------------------------------
# POST /auth/mfa/verify – Verify TOTP code during login (called with mfa_token)
# ---------------------------------------------------------------------------
@router.post("/verify")
async def mfa_verify_login(body: MFAVerifyRequest, current_user: User = Depends(require_authentication)):
    """Verify TOTP code during the login MFA challenge.
    This endpoint is called with the short-lived mfa_token.
    On success, returns the full access JWT."""
    from auth import create_access_token, create_user_session, log_auth_event
    from jose import jwt as jose_jwt

    username = current_user.username
    record = _get_mfa_record(username)

    if not record or not record["is_enabled"]:
        raise HTTPException(status_code=400, detail="MFA is not enabled for this user")

    totp = pyotp.TOTP(record["totp_secret"])
    code = body.code.strip().upper()
    verified = False

    # Try TOTP first
    if totp.verify(code, valid_window=1):
        verified = True
    else:
        # Try backup code
        stored = record.get("backup_codes") or []
        idx = _verify_backup_code(code, stored)
        if idx >= 0:
            verified = True
            # Remove used backup code
            stored.pop(idx)
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE user_mfa SET backup_codes = %s, updated_at = now() WHERE username = %s",
                        (stored, username),
                    )
                conn.commit()
            logger.info("Backup code used by %s (%d remaining)", username, len(stored))

    if not verified:
        log_auth_event(username, "mfa_failed", False)
        raise HTTPException(status_code=401, detail="Invalid MFA code")

    # Issue real JWT
    from auth import get_user_role, JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    role = get_user_role(username)
    access_token_expires = timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": username, "role": role},
        expires_delta=access_token_expires,
    )
    expires_at = datetime.utcnow() + access_token_expires

    create_user_session(username, role, access_token)
    log_auth_event(username, "mfa_verified", True)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "expires_at": expires_at.isoformat() + "Z",
        "user": {"username": username, "role": role, "is_active": True},
    }


# ---------------------------------------------------------------------------
# POST /auth/mfa/disable – Disable MFA for current user
# ---------------------------------------------------------------------------
@router.post("/disable")
async def mfa_disable(
    body: MFADisableRequest,
    current_user: User = Depends(require_authentication),
):
    """Disable MFA. Requires current TOTP code for verification."""
    username = current_user.username
    record = _get_mfa_record(username)

    if not record or not record["is_enabled"]:
        raise HTTPException(status_code=400, detail="MFA is not enabled")

    totp = pyotp.TOTP(record["totp_secret"])
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_mfa WHERE username = %s", (username,))
        conn.commit()

    logger.info("MFA disabled for %s", username)
    return {"detail": "MFA disabled successfully"}


# ---------------------------------------------------------------------------
# GET /auth/mfa/status – Check MFA status for current user
# ---------------------------------------------------------------------------
@router.get("/status", response_model=MFAStatusResponse)
async def mfa_status(current_user: User = Depends(require_authentication)):
    """Check if MFA is enabled for the current user."""
    record = _get_mfa_record(current_user.username)
    if not record or not record["is_enabled"]:
        return MFAStatusResponse(enabled=False)
    return MFAStatusResponse(
        enabled=True,
        created_at=record["created_at"].isoformat() if record.get("created_at") else None,
    )


# ---------------------------------------------------------------------------
# GET /auth/mfa/users – List MFA status for all users (admin+)
# ---------------------------------------------------------------------------
@router.get("/users", response_model=list[MFAUserListItem])
async def mfa_user_list(
    _perm=Depends(require_permission("mfa", "read")),
    current_user: User = Depends(require_authentication),
):
    """List MFA enrollment status for all users. Admin+ only."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT ur.username,
                       COALESCE(m.is_enabled, false) AS mfa_enabled,
                       m.created_at
                FROM user_roles ur
                LEFT JOIN user_mfa m ON m.username = ur.username
                WHERE ur.is_active = true
                ORDER BY ur.username
                """
            )
            rows = cur.fetchall()

    return [
        MFAUserListItem(
            username=r["username"],
            mfa_enabled=r["mfa_enabled"],
            created_at=r["created_at"].isoformat() if r.get("created_at") else None,
        )
        for r in rows
    ]
