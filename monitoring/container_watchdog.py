"""
container_watchdog.py — polls the Docker Engine API via Unix socket and sends
SMTP alerts when containers enter an unhealthy/exited state (or recover).

Started as a daemon thread from monitoring/main.py on service startup.

Environment variables consumed (all optional with safe defaults):
  DOCKER_SOCKET          path to Docker Unix socket  (default: /var/run/docker.sock)
  WATCHDOG_INTERVAL      poll interval in seconds     (default: 60)
  WATCHDOG_COOLDOWN      min seconds between alerts per container (default: 1800)
  API_BASE_URL           URL of pf9_api to fetch alert email (default: http://pf9_api:8000)
  SMTP_ENABLED           must be "true" to send email
  SMTP_HOST, SMTP_PORT, SMTP_USE_TLS, SMTP_USERNAME, SMTP_PASSWORD,
  SMTP_FROM_ADDRESS, SMTP_FROM_NAME
"""

import json
import logging
import os
import re
import smtplib
import socket
import ssl
import threading
import time
import http.client
import urllib.request
import urllib.error
from email.message import EmailMessage
from typing import Dict, Optional

logger = logging.getLogger("pf9_monitoring")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_DOCKER_SOCKET = os.getenv("DOCKER_SOCKET", "/var/run/docker.sock")
_POLL_INTERVAL = int(os.getenv("WATCHDOG_INTERVAL", "60"))
_COOLDOWN = int(os.getenv("WATCHDOG_COOLDOWN", "1800"))
_API_BASE = os.getenv("API_BASE_URL", "http://pf9_api:8000").rstrip("/")


# ---------------------------------------------------------------------------
# Docker socket HTTP client
# ---------------------------------------------------------------------------
class _UnixSocketConn(http.client.HTTPConnection):
    """HTTP client that routes over a Unix domain socket instead of TCP."""

    def __init__(self, socket_path: str):
        super().__init__("localhost")
        self._socket_path = socket_path

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self._socket_path)
        self.sock = sock


def _docker_get(path: str) -> list:
    """Perform a GET against the Docker Engine API; returns parsed JSON."""
    conn = _UnixSocketConn(_DOCKER_SOCKET)
    try:
        conn.request("GET", path, headers={"Accept": "application/json"})
        resp = conn.getresponse()
        body = resp.read()
        if resp.status != 200:
            raise RuntimeError(f"Docker API {path} returned HTTP {resp.status}: {body[:200]}")
        return json.loads(body)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Alert email retrieval
# ---------------------------------------------------------------------------
def _fetch_alert_email() -> str:
    """Fetch the configured alert email from the pf9_api settings endpoint."""
    try:
        url = f"{_API_BASE}/settings/container-alert"
        with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 — internal service
            data = json.loads(resp.read())
            return data.get("value", "").strip()
    except Exception as exc:
        logger.warning("Could not fetch container alert email: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# SMTP alert
# ---------------------------------------------------------------------------
def _send_alert(to_addr: str, subject: str, body: str) -> None:
    """Send a plain-text alert email using SMTP env-var config."""
    if os.getenv("SMTP_ENABLED", "false").lower() != "true":
        logger.info("SMTP disabled — skipping alert: %s", subject)
        return
    if not to_addr:
        logger.warning("Container alert email not configured — skipping alert: %s", subject)
        return

    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "587"))
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    username = os.getenv("SMTP_USERNAME", "")
    password = os.getenv("SMTP_PASSWORD", "")
    from_addr = os.getenv("SMTP_FROM_ADDRESS", "pf9-mgmt@example.com")
    from_name = os.getenv("SMTP_FROM_NAME", "Platform9 Management")

    if not host:
        logger.warning("SMTP_HOST not set — skipping alert: %s", subject)
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = to_addr
    msg.set_content(body)

    try:
        if use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.ehlo()
                server.starttls(context=context)
                if username:
                    server.login(username, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                if username:
                    server.login(username, password)
                server.send_message(msg)
        logger.info("Container alert sent to %s: %s", to_addr, subject)
    except Exception as exc:
        logger.error("Failed to send container alert email: %s", exc)


# ---------------------------------------------------------------------------
# Health evaluation helpers
# ---------------------------------------------------------------------------
_EXIT_CODE_RE = re.compile(r"Exited \((\d+)\)")


def _is_unhealthy(container: dict) -> Optional[str]:
    """
    Return a human-readable reason string if the container is unhealthy,
    or None if it is considered healthy.
    """
    state = (container.get("State") or "").lower()
    status = container.get("Status") or ""

    if state == "exited":
        m = _EXIT_CODE_RE.search(status)
        exit_code = int(m.group(1)) if m else -1
        if exit_code != 0:
            return f"exited with code {exit_code}"
        return None  # clean exit (exit 0) is intentional

    if "unhealthy" in status.lower():
        return "Docker healthcheck reported unhealthy"

    return None


# ---------------------------------------------------------------------------
# Watchdog loop
# ---------------------------------------------------------------------------

def _run_watchdog() -> None:
    last_alerted: Dict[str, float] = {}   # container_name → timestamp of last alert
    known_unhealthy: Dict[str, bool] = {} # container_name → True if currently unhealthy

    logger.info(
        "Container watchdog started (socket=%s, interval=%ss, cooldown=%ss)",
        _DOCKER_SOCKET, _POLL_INTERVAL, _COOLDOWN,
    )

    while True:
        try:
            containers = _docker_get("/containers/json?all=1")
        except FileNotFoundError:
            logger.warning(
                "Docker socket %s not found — container watchdog disabled (expected in dev mode).",
                _DOCKER_SOCKET,
            )
            return  # Silently exit thread; service continues normally
        except Exception as exc:
            logger.error("Docker API poll error: %s", exc)
            time.sleep(_POLL_INTERVAL)
            continue

        alert_email = _fetch_alert_email()
        now = time.time()

        for c in containers:
            names = c.get("Names") or []
            name = names[0].lstrip("/") if names else c.get("Id", "unknown")[:12]
            reason = _is_unhealthy(c)

            if reason:
                was_unhealthy = known_unhealthy.get(name, False)
                known_unhealthy[name] = True
                last_alert = last_alerted.get(name, 0.0)
                if now - last_alert < _COOLDOWN:
                    continue  # within cooldown window
                last_alerted[name] = now
                subject = f"[PF9 Alert] Container '{name}' is unhealthy"
                body = (
                    f"Container health alert\n"
                    f"{'='*40}\n"
                    f"Container : {name}\n"
                    f"Reason    : {reason}\n"
                    f"Status    : {c.get('Status', 'unknown')}\n"
                    f"Image     : {c.get('Image', 'unknown')}\n"
                    f"Detected  : {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(now))}\n\n"
                    f"Please investigate and restart the container if necessary.\n"
                    f"Use: docker restart {name}\n"
                )
                logger.warning("Unhealthy container detected: %s (%s)", name, reason)
                _send_alert(alert_email, subject, body)

            else:
                # Container is healthy — send recovery alert if it was previously unhealthy
                if known_unhealthy.pop(name, False):
                    last_alerted.pop(name, None)  # reset cooldown so future failures alert again
                    subject = f"[PF9 Recovery] Container '{name}' is healthy again"
                    body = (
                        f"Container recovery notification\n"
                        f"{'='*40}\n"
                        f"Container : {name}\n"
                        f"Status    : {c.get('Status', 'unknown')}\n"
                        f"Image     : {c.get('Image', 'unknown')}\n"
                        f"Recovered : {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(now))}\n"
                    )
                    logger.info("Container recovered: %s", name)
                    _send_alert(alert_email, subject, body)

        time.sleep(_POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_watchdog() -> None:
    """Launch the container watchdog as a background daemon thread."""
    t = threading.Thread(target=_run_watchdog, name="container-watchdog", daemon=True)
    t.start()
