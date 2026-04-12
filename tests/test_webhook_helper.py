"""
tests/test_webhook_helper.py — Unit tests for api/webhook_helper.py

No live network calls.  urllib.request.urlopen is mocked throughout.
"""
import os
import sys
import types
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_API_DIR = os.path.join(os.path.dirname(__file__), "..", "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

import webhook_helper  # noqa: E402


# ---------------------------------------------------------------------------
# Tests: _valid_webhook_url
# ---------------------------------------------------------------------------
class TestValidWebhookUrl:
    def test_valid_https_url_accepted(self):
        url = "https://hooks.slack.com/services/T00/B00/abc"
        assert webhook_helper._valid_webhook_url(url) == url

    def test_http_url_rejected(self):
        assert webhook_helper._valid_webhook_url("http://hooks.slack.com/abc") == ""

    def test_empty_string_returns_empty(self):
        assert webhook_helper._valid_webhook_url("") == ""

    def test_no_host_rejected(self):
        assert webhook_helper._valid_webhook_url("https://") == ""

    def test_non_url_string_rejected(self):
        assert webhook_helper._valid_webhook_url("not-a-url") == ""


# ---------------------------------------------------------------------------
# Tests: send_slack
# ---------------------------------------------------------------------------
class TestSendSlack:
    def test_returns_false_when_not_configured(self, monkeypatch):
        monkeypatch.setattr(webhook_helper, "SLACK_WEBHOOK_URL", "")
        assert webhook_helper.send_slack("subj", "body") is False

    def test_returns_true_on_success(self, monkeypatch):
        monkeypatch.setattr(webhook_helper, "SLACK_WEBHOOK_URL",
                            "https://hooks.slack.com/services/T/B/X")
        with patch.object(webhook_helper, "_post_json", return_value=None):
            assert webhook_helper.send_slack("Alert", "Something happened") is True

    def test_returns_false_on_post_failure(self, monkeypatch):
        monkeypatch.setattr(webhook_helper, "SLACK_WEBHOOK_URL",
                            "https://hooks.slack.com/services/T/B/X")
        with patch.object(webhook_helper, "_post_json",
                          side_effect=RuntimeError("HTTP 500")):
            assert webhook_helper.send_slack("Alert", "body") is False

    def test_event_type_included_in_payload(self, monkeypatch):
        monkeypatch.setattr(webhook_helper, "SLACK_WEBHOOK_URL",
                            "https://hooks.slack.com/services/T/B/X")
        captured = {}
        def _fake_post(url, payload, timeout=15):
            captured["payload"] = payload
        with patch.object(webhook_helper, "_post_json", side_effect=_fake_post):
            webhook_helper.send_slack("Alert", "body", event_type="vm_alert")
        text = str(captured.get("payload", ""))
        assert "vm_alert" in text

    def test_body_truncated_to_2000_chars(self, monkeypatch):
        monkeypatch.setattr(webhook_helper, "SLACK_WEBHOOK_URL",
                            "https://hooks.slack.com/services/T/B/X")
        captured = {}
        def _fake_post(url, payload, timeout=15):
            captured["payload"] = payload
        with patch.object(webhook_helper, "_post_json", side_effect=_fake_post):
            long_body = "x" * 3000
            webhook_helper.send_slack("Subject", long_body)
        blocks = captured["payload"]["blocks"]
        body_block = next(b for b in blocks if b.get("type") == "section"
                          and b.get("text", {}).get("type") == "plain_text")
        assert len(body_block["text"]["text"]) <= 2000


# ---------------------------------------------------------------------------
# Tests: send_teams
# ---------------------------------------------------------------------------
class TestSendTeams:
    def test_returns_false_when_not_configured(self, monkeypatch):
        monkeypatch.setattr(webhook_helper, "TEAMS_WEBHOOK_URL", "")
        assert webhook_helper.send_teams("subj", "body") is False

    def test_returns_true_on_success(self, monkeypatch):
        monkeypatch.setattr(webhook_helper, "TEAMS_WEBHOOK_URL",
                            "https://outlook.office.com/webhook/abc")
        with patch.object(webhook_helper, "_post_json", return_value=None):
            assert webhook_helper.send_teams("Alert", "body") is True

    def test_returns_false_on_post_failure(self, monkeypatch):
        monkeypatch.setattr(webhook_helper, "TEAMS_WEBHOOK_URL",
                            "https://outlook.office.com/webhook/abc")
        with patch.object(webhook_helper, "_post_json",
                          side_effect=urllib.error.URLError("connection refused")):
            assert webhook_helper.send_teams("Alert", "body") is False

    def test_payload_has_message_card_type(self, monkeypatch):
        monkeypatch.setattr(webhook_helper, "TEAMS_WEBHOOK_URL",
                            "https://outlook.office.com/webhook/abc")
        captured = {}
        def _fake_post(url, payload, timeout=15):
            captured["payload"] = payload
        with patch.object(webhook_helper, "_post_json", side_effect=_fake_post):
            webhook_helper.send_teams("Alert", "body")
        assert captured["payload"]["@type"] == "MessageCard"


# ---------------------------------------------------------------------------
# Tests: post_event (unified dispatch)
# ---------------------------------------------------------------------------
class TestPostEvent:
    def test_returns_none_for_unconfigured_channels(self, monkeypatch):
        monkeypatch.setattr(webhook_helper, "SLACK_ENABLED", False)
        monkeypatch.setattr(webhook_helper, "TEAMS_ENABLED", False)
        result = webhook_helper.post_event("test_event", "Subject", "Body")
        assert result == {"slack": None, "teams": None}

    def test_returns_true_for_configured_and_successful_slack(self, monkeypatch):
        monkeypatch.setattr(webhook_helper, "SLACK_ENABLED", True)
        monkeypatch.setattr(webhook_helper, "TEAMS_ENABLED", False)
        monkeypatch.setattr(webhook_helper, "SLACK_WEBHOOK_URL",
                            "https://hooks.slack.com/services/T/B/X")
        with patch.object(webhook_helper, "_post_json", return_value=None):
            result = webhook_helper.post_event("ev", "Subject", "Body")
        assert result["slack"] is True
        assert result["teams"] is None

    def test_returns_false_for_configured_but_failing_channel(self, monkeypatch):
        monkeypatch.setattr(webhook_helper, "SLACK_ENABLED", True)
        monkeypatch.setattr(webhook_helper, "TEAMS_ENABLED", False)
        monkeypatch.setattr(webhook_helper, "SLACK_WEBHOOK_URL",
                            "https://hooks.slack.com/services/T/B/X")
        with patch.object(webhook_helper, "_post_json",
                          side_effect=RuntimeError("HTTP 500")):
            result = webhook_helper.post_event("ev", "Subject", "Body")
        assert result["slack"] is False

    def test_dispatches_to_both_channels(self, monkeypatch):
        monkeypatch.setattr(webhook_helper, "SLACK_ENABLED", True)
        monkeypatch.setattr(webhook_helper, "TEAMS_ENABLED", True)
        monkeypatch.setattr(webhook_helper, "SLACK_WEBHOOK_URL",
                            "https://hooks.slack.com/services/T/B/X")
        monkeypatch.setattr(webhook_helper, "TEAMS_WEBHOOK_URL",
                            "https://outlook.office.com/webhook/abc")
        calls = []
        def _fake_post(url, payload, timeout=15):
            calls.append(url)
        with patch.object(webhook_helper, "_post_json", side_effect=_fake_post):
            result = webhook_helper.post_event("ev", "Subject", "Body")
        assert result["slack"] is True
        assert result["teams"] is True
        assert len(calls) == 2
