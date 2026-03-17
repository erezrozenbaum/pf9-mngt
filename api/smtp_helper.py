"""
smtp_helper.py — Centralised SMTP configuration and send helpers.

All modules that send email should import from here instead of
duplicating the SMTP_* env-var reads and transport logic.

Exported symbols
----------------
SMTP_ENABLED, SMTP_HOST, SMTP_PORT, SMTP_USE_TLS,
SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_ADDRESS, SMTP_FROM_NAME

send_email(to_addrs, subject, html_body, *, raise_on_error=False) -> bool
    Build a MIMEMultipart/alternative message and deliver it.
    Returns True on success, False on delivery failure (unless raise_on_error=True).

send_raw(msg, to_addrs)
    Deliver a pre-built MIME message.  Raises on failure.
    Used by callers that build their own MIMEMultipart (e.g. personalised emails).
"""
import os
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Union

logger = logging.getLogger("pf9_smtp")

# ---------------------------------------------------------------------------
# SMTP configuration (single source of truth for the whole application)
# ---------------------------------------------------------------------------
SMTP_ENABLED      = os.getenv("SMTP_ENABLED", "false").lower() in ("true", "1", "yes")
SMTP_HOST         = os.getenv("SMTP_HOST", "")
SMTP_PORT         = int(os.getenv("SMTP_PORT", "587"))
SMTP_USE_TLS      = os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")
SMTP_USERNAME     = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD     = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_ADDRESS = os.getenv("SMTP_FROM_ADDRESS", "pf9-mgmt@example.com")
SMTP_FROM_NAME    = os.getenv("SMTP_FROM_NAME", "Platform9 Management")


# ---------------------------------------------------------------------------
# Internal transport
# ---------------------------------------------------------------------------
def _do_send(msg, to_addrs: List[str]) -> None:
    """Low-level SMTP transport.  Raises smtplib exceptions on failure."""
    if SMTP_USE_TLS:
        ctx = ssl.create_default_context()
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.ehlo()
            if SMTP_USERNAME:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM_ADDRESS, to_addrs, msg.as_string())
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            if SMTP_USERNAME:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM_ADDRESS, to_addrs, msg.as_string())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def send_email(
    to_addrs: Union[str, List[str]],
    subject: str,
    html_body: str,
    *,
    raise_on_error: bool = False,
) -> bool:
    """Build and deliver an HTML email.

    Parameters
    ----------
    to_addrs : str or list[str]
        Recipient address(es).
    subject : str
        Email subject line.
    html_body : str
        HTML content for the message body.
    raise_on_error : bool, optional
        When True, re-raise smtplib exceptions instead of logging and
        returning False.  Set this for interactive routes that surface
        SMTP errors directly to the user (e.g. /test-email).

    Returns
    -------
    bool
        True on success; False on delivery failure (when raise_on_error=False).
    """
    if not SMTP_ENABLED or not SMTP_HOST:
        logger.info("SMTP disabled — would send '%s' to %s", subject, to_addrs)
        return True

    if isinstance(to_addrs, str):
        to_addrs = [to_addrs]

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_ADDRESS}>"
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    try:
        _do_send(msg, to_addrs)
        return True
    except smtplib.SMTPAuthenticationError:
        if raise_on_error:
            raise
        logger.error("SMTP authentication failed sending '%s'", subject)
        return False
    except smtplib.SMTPConnectError:
        if raise_on_error:
            raise
        logger.error("SMTP connect failed to %s:%s", SMTP_HOST, SMTP_PORT)
        return False
    except Exception as exc:
        if raise_on_error:
            raise
        logger.error("Failed to send email to %s: %s", to_addrs, exc)
        return False


def send_raw(msg, to_addrs: Union[str, List[str]]) -> None:
    """Deliver a pre-built MIME message.  Raises on failure.

    Use this when the caller assembles its own MIMEMultipart (e.g. when
    sending personalised per-user emails with custom From/To headers).
    """
    if isinstance(to_addrs, str):
        to_addrs = [to_addrs]
    _do_send(msg, to_addrs)
