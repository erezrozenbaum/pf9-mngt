"""
Regression tests for smart query matching and formatter correctness.
"""

import os
import sys
import types
from typing import Any, Dict, List

_API_DIR = os.path.join(os.path.dirname(__file__), "..", "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

# Stub copilot_llm so smart_queries can import in isolation.
_copilot_llm_stub = types.ModuleType("copilot_llm")
_copilot_llm_stub.ask_llm = lambda *a, **k: ("", "builtin", 0, None)
sys.modules.setdefault("copilot_llm", _copilot_llm_stub)

from smart_queries import execute_smart_query  # noqa: E402


class _FakeCursor:
    def __init__(self, rows: List[Dict[str, Any]], state: Dict[str, Any]):
        self._rows = rows
        self._state = state

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params: Dict[str, Any]):
        self._state["last_sql"] = sql
        self._state["last_params"] = params

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows: List[Dict[str, Any]]):
        self.state: Dict[str, Any] = {}
        self.rows = rows

    def cursor(self, cursor_factory=None):
        return _FakeCursor(self.rows, self.state)


def test_running_vm_query_beats_generic_vm_count():
    conn = _FakeConn([
        {
            "name": "vm-a",
            "project": "tenant-a",
            "domain": "domain-a",
            "host": "hv-1",
            "created_at": None,
        }
    ])

    result = execute_smart_query("how many running vms", conn)

    assert result is not None
    assert result["query_id"] == "running_vms"
    assert "status = 'ACTIVE'" in conn.state["last_sql"]


def test_generic_vm_count_still_works_for_plain_count_question():
    conn = _FakeConn([{"count": 7}])

    result = execute_smart_query("how many vms", conn)

    assert result is not None
    assert result["query_id"] == "vm_count"
    assert result["card_type"] == "number"
    assert result["value"] == 7


def test_backup_history_summary_uses_lifecycle_statuses():
    conn = _FakeConn([
        {"backup_type": "database", "status": "completed", "started_at": None, "finished_at": None, "file_size_mb": 10.5, "error_message": None},
        {"backup_type": "database", "status": "running", "started_at": None, "finished_at": None, "file_size_mb": 0, "error_message": None},
        {"backup_type": "ldap", "status": "pending", "started_at": None, "finished_at": None, "file_size_mb": 0, "error_message": None},
        {"backup_type": "ldap", "status": "failed", "started_at": None, "finished_at": None, "file_size_mb": 0, "error_message": "boom"},
    ])

    result = execute_smart_query("backup history", conn)

    assert result is not None
    assert result["query_id"] == "backup_history"
    assert "1 completed" in result["summary"]
    assert "1 running" in result["summary"]
    assert "1 pending" in result["summary"]
    assert "1 failed" in result["summary"]
