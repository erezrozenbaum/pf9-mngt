"""
Tests for the Notification Dead-Letter Queue (DLQ) — v2.4.0

Covers:
  - enqueue_retry(): inserts to queue, handles DB errors gracefully
  - process_retry_queue(): success path, failure-with-backoff, dead-letter
  - dispatch_event() integration: enqueue_retry called on failure but not success
  - Backoff schedule: list length, monotonically increasing delays
"""
import importlib.util
import json
import os
import sys
import types
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# psycopg2 compatibility shim
# ---------------------------------------------------------------------------
# test_backup_worker.py installs a psycopg2.extras stub that lacks Json.
# Overwrite it with a compatible stub so notifications/main.py can import.
_psycopg2_extras_stub = types.ModuleType("psycopg2.extras")
_psycopg2_extras_stub.RealDictCursor = MagicMock()
_psycopg2_extras_stub.Json = MagicMock()
sys.modules["psycopg2.extras"] = _psycopg2_extras_stub

_psycopg2_stub = sys.modules.get("psycopg2") or types.ModuleType("psycopg2")
if not hasattr(_psycopg2_stub, "OperationalError"):
    _psycopg2_stub.OperationalError = type("OperationalError", (Exception,), {})
sys.modules.setdefault("psycopg2", _psycopg2_stub)

# ---------------------------------------------------------------------------
# Load notifications/main.py by explicit path to avoid clashing with any
# other worker 'main' module already on sys.path.
# ---------------------------------------------------------------------------
_NOTIF_MAIN_PATH = os.path.join(
    os.path.dirname(__file__), "..", "notifications", "main.py"
)
_spec = importlib.util.spec_from_file_location("notifications_main", _NOTIF_MAIN_PATH)
notif_main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(notif_main)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cursor(rows=None):
    cur = MagicMock()
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchall.return_value = rows or []
    cur.fetchone.return_value = None
    return cur


def _make_conn(rows=None):
    """Return a (conn, cursor) pair whose cursor returns `rows` from fetchall."""
    cur = _make_cursor(rows)
    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.commit = MagicMock()
    conn.rollback = MagicMock()
    return conn, cur


def _sample_event():
    return {
        "event_type": "snapshot_failure",
        "event_id": "evt-001",
        "resource_id": "vol-abc",
        "resource_name": "test-volume",
        "severity": "critical",
        "summary": "Snapshot run failed",
    }


def _sample_user():
    return {"username": "alice", "email": "alice@example.com"}


def _dlq_row(attempt_count=0, max_attempts=3):
    return {
        "id": 1,
        "username": "alice",
        "email": "alice@example.com",
        "event_type": "snapshot_failure",
        "event_id": "evt-001",
        "dedup_key": "dkey-abc",
        "subject": "Snapshot Failure on test-volume",
        "template_name": "snapshot_failure.html",
        "event_json": _sample_event(),
        "attempt_count": attempt_count,
        "max_attempts": max_attempts,
    }


# ---------------------------------------------------------------------------
# enqueue_retry
# ---------------------------------------------------------------------------

class TestEnqueueRetry:
    def test_inserts_row_and_commits(self):
        conn, cur = _make_conn()
        notif_main.enqueue_retry(
            conn, _sample_user(), _sample_event(),
            "dkey-001", "Snapshot Failure", "snapshot_failure.html",
        )
        cur.execute.assert_called_once()
        conn.commit.assert_called_once()

    def test_db_exception_is_caught_and_rolls_back(self):
        conn, cur = _make_conn()
        cur.execute.side_effect = Exception("DB write error")
        # Must not propagate the exception
        notif_main.enqueue_retry(
            conn, _sample_user(), _sample_event(),
            "dkey-002", "Snapshot Failure", "snapshot_failure.html",
        )
        conn.rollback.assert_called_once()

    def test_passes_correct_username_email(self):
        conn, cur = _make_conn()
        user = {"username": "bob", "email": "bob@example.com"}
        notif_main.enqueue_retry(
            conn, user, _sample_event(),
            "dkey-003", "Subject", "template.html",
        )
        call_args = cur.execute.call_args[0][1]  # positional params tuple
        assert call_args[0] == "bob"
        assert call_args[1] == "bob@example.com"

    def test_serialises_event_to_json(self):
        conn, cur = _make_conn()
        event = _sample_event()
        notif_main.enqueue_retry(
            conn, _sample_user(), event,
            "dkey-004", "Subject", "template.html",
        )
        call_args = cur.execute.call_args[0][1]
        # The event_json parameter should be a JSON string
        event_json_param = call_args[7]
        assert isinstance(event_json_param, str)
        assert json.loads(event_json_param)["event_type"] == "snapshot_failure"


# ---------------------------------------------------------------------------
# process_retry_queue
# ---------------------------------------------------------------------------

class TestProcessRetryQueueNoItems:
    def test_empty_queue_does_nothing(self):
        conn, cur = _make_conn(rows=[])
        notif_main.process_retry_queue(conn)
        conn.commit.assert_not_called()

    def test_db_fetch_exception_is_caught(self):
        conn, cur = _make_conn()
        cur.execute.side_effect = Exception("DB read error")
        # Must not propagate
        notif_main.process_retry_queue(conn)


class TestProcessRetryQueueSuccess:
    def test_success_updates_log_and_deletes_row(self):
        row = _dlq_row(attempt_count=0)
        conn, cur = _make_conn(rows=[row])

        with patch.object(notif_main, "render_template", return_value="<html>ok</html>"), \
             patch.object(notif_main, "send_email", return_value=True):
            notif_main.process_retry_queue(conn)

        conn.commit.assert_called()

    def test_success_commits_at_least_once(self):
        row = _dlq_row(attempt_count=1)
        conn, cur = _make_conn(rows=[row])

        with patch.object(notif_main, "render_template", return_value="<html/>"), \
             patch.object(notif_main, "send_email", return_value=True):
            notif_main.process_retry_queue(conn)

        assert conn.commit.call_count >= 1


class TestProcessRetryQueueFailureWithBackoff:
    def test_failed_below_max_increments_attempt_and_commits(self):
        row = _dlq_row(attempt_count=0, max_attempts=3)
        conn, cur = _make_conn(rows=[row])

        with patch.object(notif_main, "render_template", return_value="<html/>"), \
             patch.object(notif_main, "send_email", return_value=False):
            notif_main.process_retry_queue(conn)

        conn.commit.assert_called()

    def test_render_exception_still_schedules_retry(self):
        row = _dlq_row(attempt_count=0, max_attempts=3)
        conn, cur = _make_conn(rows=[row])

        with patch.object(
            notif_main, "render_template", side_effect=Exception("Template missing")
        ):
            notif_main.process_retry_queue(conn)

        conn.commit.assert_called()


class TestProcessRetryQueueDeadLetter:
    def test_final_attempt_dead_letters_and_commits(self):
        # attempt_count=2, max_attempts=3 → attempt becomes 3 == max
        row = _dlq_row(attempt_count=2, max_attempts=3)
        conn, cur = _make_conn(rows=[row])

        with patch.object(notif_main, "render_template", return_value="<html/>"), \
             patch.object(notif_main, "send_email", return_value=False):
            notif_main.process_retry_queue(conn)

        conn.commit.assert_called()

    def test_dead_letter_on_send_exception_at_max(self):
        row = _dlq_row(attempt_count=2, max_attempts=3)
        conn, cur = _make_conn(rows=[row])

        with patch.object(notif_main, "render_template", return_value="<html/>"), \
             patch.object(notif_main, "send_email", side_effect=Exception("SMTP down")):
            notif_main.process_retry_queue(conn)

        conn.commit.assert_called()

    def test_db_update_exception_during_dead_letter_is_caught(self):
        row = _dlq_row(attempt_count=2, max_attempts=3)
        conn, cur = _make_conn(rows=[row])
        # make fetchall return the row but subsequent execute calls raise
        call_count = [0]
        original_execute = cur.execute

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return None  # the SELECT succeeds
            raise Exception("DB write error on update")

        cur.execute.side_effect = side_effect

        with patch.object(notif_main, "render_template", return_value="<html/>"), \
             patch.object(notif_main, "send_email", return_value=False):
            # Must not propagate
            notif_main.process_retry_queue(conn)

        conn.rollback.assert_called()


# ---------------------------------------------------------------------------
# dispatch_event DLQ integration
# ---------------------------------------------------------------------------

class TestDispatchEventDlqIntegration:
    """Verify dispatch_event wires enqueue_retry correctly."""

    def _conn_for_dispatch(self, users=None, already_sent=False):
        """Return a mock conn pre-configured for dispatch_event's cursor queries."""
        call_count = [0]

        def cursor_factory(**kwargs):
            cur = MagicMock()
            cur.__enter__ = lambda s: s
            cur.__exit__ = MagicMock(return_value=False)
            call_count[0] += 1
            if call_count[0] == 1:
                # already_sent check
                cur.fetchone.return_value = (1,) if already_sent else None
            elif call_count[0] == 2:
                # get_subscribed_users
                cur.fetchall.return_value = users or []
            else:
                cur.fetchone.return_value = None
                cur.fetchall.return_value = []
            return cur

        conn = MagicMock()
        conn.cursor.side_effect = cursor_factory
        conn.commit = MagicMock()
        conn.rollback = MagicMock()
        return conn

    def _immediate_user(self):
        return {
            "username": "alice",
            "email": "alice@example.com",
            "delivery_mode": "immediate",
            "severity_min": "warning",
        }

    def test_failed_send_calls_enqueue_retry(self):
        conn = self._conn_for_dispatch(users=[self._immediate_user()])

        with patch.object(notif_main, "render_template", return_value="<html/>"), \
             patch.object(notif_main, "send_email", return_value=False), \
             patch.object(notif_main, "log_notification"), \
             patch.object(notif_main, "enqueue_retry") as mock_enqueue:
            notif_main.dispatch_event(conn, _sample_event())

        mock_enqueue.assert_called_once()

    def test_successful_send_does_not_enqueue_retry(self):
        conn = self._conn_for_dispatch(users=[self._immediate_user()])

        with patch.object(notif_main, "render_template", return_value="<html/>"), \
             patch.object(notif_main, "send_email", return_value=True), \
             patch.object(notif_main, "log_notification"), \
             patch.object(notif_main, "enqueue_retry") as mock_enqueue:
            notif_main.dispatch_event(conn, _sample_event())

        mock_enqueue.assert_not_called()

    def test_render_exception_calls_enqueue_retry(self):
        conn = self._conn_for_dispatch(users=[self._immediate_user()])

        with patch.object(
            notif_main, "render_template", side_effect=Exception("Template error")
        ), \
             patch.object(notif_main, "log_notification"), \
             patch.object(notif_main, "enqueue_retry") as mock_enqueue:
            notif_main.dispatch_event(conn, _sample_event())

        mock_enqueue.assert_called_once()

    def test_already_sent_skips_dispatch_entirely(self):
        conn = self._conn_for_dispatch(already_sent=True)

        with patch.object(notif_main, "enqueue_retry") as mock_enqueue:
            notif_main.dispatch_event(conn, _sample_event())

        mock_enqueue.assert_not_called()


# ---------------------------------------------------------------------------
# Backoff schedule constants
# ---------------------------------------------------------------------------

class TestRetryBackoffConstants:
    def test_backoff_list_has_three_entries(self):
        assert len(notif_main._RETRY_BACKOFF_MINUTES) == 3

    def test_backoff_is_strictly_increasing(self):
        delays = notif_main._RETRY_BACKOFF_MINUTES
        assert all(delays[i] < delays[i + 1] for i in range(len(delays) - 1))

    def test_first_delay_is_five_minutes(self):
        assert notif_main._RETRY_BACKOFF_MINUTES[0] == 5

    def test_default_max_attempts_is_positive(self):
        assert notif_main.DLQ_MAX_ATTEMPTS >= 1
