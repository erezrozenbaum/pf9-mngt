import sys
from pathlib import Path
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

auth_stub = types.ModuleType("auth")
auth_stub.require_permission = lambda *_args, **_kwargs: (lambda: {"username": "admin"})
auth_stub.User = dict
sys.modules.setdefault("auth", auth_stub)

db_pool_stub = types.ModuleType("db_pool")
db_pool_stub.get_connection = lambda: None
sys.modules.setdefault("db_pool", db_pool_stub)

import sla_defense_routes as routes  # noqa: E402
from fastapi import HTTPException  # noqa: E402


class _FakeCursor:
    def __init__(self, rows=None, rowcount=1):
        self.rows = rows or []
        self.rowcount = rowcount
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self.rows


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, cursor_factory=None):  # noqa: ARG002
        return self._cursor

    def commit(self):
        self.committed = True


def test_alerts_summary_returns_counts(monkeypatch):
    rows = [{"severity": "warning", "count": 2}, {"severity": "critical", "count": 1}]
    cur = _FakeCursor(rows=rows)
    conn = _FakeConn(cur)
    monkeypatch.setattr(routes, "get_connection", lambda: conn)

    result = routes.alerts_summary(_user={"username": "admin"})

    assert result["open"]["warning"] == 2
    assert result["open"]["critical"] == 1
    assert result["total_open"] == 3


def test_dismiss_alert_commits(monkeypatch):
    cur = _FakeCursor(rowcount=1)
    conn = _FakeConn(cur)
    monkeypatch.setattr(routes, "get_connection", lambda: conn)

    result = routes.dismiss_alert(7, routes.AlertActionBody(note="handled"), _user={"username": "admin"})

    assert result["ok"] is True
    assert result["status"] == "dismissed"
    assert conn.committed is True


def test_dismiss_alert_404_when_missing(monkeypatch):
    cur = _FakeCursor(rowcount=0)
    conn = _FakeConn(cur)
    monkeypatch.setattr(routes, "get_connection", lambda: conn)

    try:
        routes.dismiss_alert(7, routes.AlertActionBody(note="handled"), _user={"username": "admin"})
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 404


def test_resolve_alert_commits(monkeypatch):
    cur = _FakeCursor(rowcount=1)
    conn = _FakeConn(cur)
    monkeypatch.setattr(routes, "get_connection", lambda: conn)

    result = routes.resolve_alert(9, routes.AlertActionBody(note="done"), _user={"username": "admin"})

    assert result["ok"] is True
    assert result["status"] == "resolved"
    assert conn.committed is True
