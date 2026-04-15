"""
webhook_helper.py — Slack and Microsoft Teams outgoing webhook helpers.

Reads webhook URLs from environment variables:
  SLACK_WEBHOOK_URL   — Slack incoming-webhook URL
  TEAMS_WEBHOOK_URL   — MS Teams incoming-webhook (Office 365 Connector) URL

Exported symbols
----------------
SLACK_ENABLED   bool  — True when SLACK_WEBHOOK_URL is set
TEAMS_ENABLED   bool  — True when TEAMS_WEBHOOK_URL is set

send_slack(subject, body_text, *, event_type="", color="#0076D7") -> bool
    POST a Slack Block Kit message.  Returns True on success.

send_teams(subject, body_text, *, event_type="", color="0076D7") -> bool
    POST an MS Teams MessageCard.  Returns True on success.

post_event(event_type, subject, body_text) -> dict
    Dispatch to every configured channel.  Returns:
    {"slack": True|False|None, "teams": True|False|None}
    None means that channel is not configured.
"""

import json
import logging
import os
import urllib.parse
import urllib.request
import urllib.error
from typing import Optional

logger = logging.getLogger("pf9_webhook")


def _valid_webhook_url(url: str) -> str:
    """Return *url* if it is a valid https URL; otherwise log a warning and return ''."""
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        logger.warning(
            "Webhook URL rejected (must be https with non-empty host): %s",
            url[:80],
        )
        return ""
    return url


# ---------------------------------------------------------------------------
# Configuration (single source of truth)
# ---------------------------------------------------------------------------
SLACK_WEBHOOK_URL: str = _valid_webhook_url(os.getenv("SLACK_WEBHOOK_URL", ""))
TEAMS_WEBHOOK_URL: str = _valid_webhook_url(os.getenv("TEAMS_WEBHOOK_URL", ""))

SLACK_ENABLED: bool = bool(SLACK_WEBHOOK_URL)
TEAMS_ENABLED: bool = bool(TEAMS_WEBHOOK_URL)


# ---------------------------------------------------------------------------
# Internal POST helper
# ---------------------------------------------------------------------------
def _post_json(url: str, payload: dict, timeout: int = 15) -> None:
    """POST *payload* as JSON to *url*.  Raises on non-2xx or network error."""
    # Restrict to http/https only — reject file:// and other schemes (SSRF prevention)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Webhook URL scheme '{parsed.scheme}' is not allowed; use http or https")
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 — scheme validated above
        status = resp.getcode()
    if status < 200 or status >= 300:
        raise RuntimeError(f"Webhook returned HTTP {status}")


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------
def send_slack(
    subject: str,
    body_text: str,
    *,
    event_type: str = "",
    color: str = "#0076D7",
) -> bool:
    """Post a Block Kit message to the configured Slack incoming webhook.

    Returns True on success, False on failure (always logs errors).
    """
    if not SLACK_WEBHOOK_URL:
        logger.debug("Slack webhook not configured — skipping")
        return False

    header = f"*PF9 Management*"
    if event_type:
        header += f" · `{event_type}`"

    payload = {
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"{header}\n*{subject}*"},
            },
            {
                "type": "section",
                "text": {"type": "plain_text", "text": body_text[:2000], "emoji": False},
            },
        ],
        "attachments": [{"color": color, "fallback": subject}],
    }

    try:
        _post_json(SLACK_WEBHOOK_URL, payload)
        logger.info("Slack notification sent: %s", subject)
        return True
    except Exception as exc:
        logger.error("Failed to send Slack notification: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Microsoft Teams
# ---------------------------------------------------------------------------
def send_teams(
    subject: str,
    body_text: str,
    *,
    event_type: str = "",
    color: str = "0076D7",
) -> bool:
    """Post a MessageCard to the configured MS Teams incoming webhook.

    Returns True on success, False on failure.
    """
    if not TEAMS_WEBHOOK_URL:
        logger.debug("Teams webhook not configured — skipping")
        return False

    title = "PF9 Management"
    if event_type:
        title += f" — {event_type}"

    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": color,
        "summary": subject,
        "sections": [
            {
                "activityTitle": title,
                "activitySubtitle": subject,
                "activityText": body_text[:2000],
                "markdown": False,
            }
        ],
    }

    try:
        _post_json(TEAMS_WEBHOOK_URL, payload)
        logger.info("Teams notification sent: %s", subject)
        return True
    except Exception as exc:
        logger.error("Failed to send Teams notification: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Unified dispatch
# ---------------------------------------------------------------------------
def post_event(
    event_type: str,
    subject: str,
    body_text: str,
) -> dict:
    """Send *subject* / *body_text* to every configured webhook channel.

    Returns a dict with the outcome per channel:
      - True  = sent successfully
      - False = configured but send failed
      - None  = channel not configured
    """
    result: dict = {"slack": None, "teams": None}

    if SLACK_ENABLED:
        result["slack"] = send_slack(subject, body_text, event_type=event_type)

    if TEAMS_ENABLED:
        result["teams"] = send_teams(subject, body_text, event_type=event_type)

    return result
