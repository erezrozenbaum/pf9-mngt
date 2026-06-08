import importlib
import sys
import types
from pathlib import Path

# Allow importing api modules as top-level modules.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))


auth_stub = types.ModuleType("auth")
auth_stub.User = dict
auth_stub.require_permission = lambda *_args, **_kwargs: (lambda: {"username": "admin"})

db_pool_stub = types.ModuleType("db_pool")
db_pool_stub.get_connection = lambda: None

_prev_auth = sys.modules.get("auth")
_prev_db_pool = sys.modules.get("db_pool")
sys.modules["auth"] = auth_stub
sys.modules["db_pool"] = db_pool_stub

thr = importlib.import_module("tenant_health_routes")

if _prev_auth is None:
    del sys.modules["auth"]
else:
    sys.modules["auth"] = _prev_auth

if _prev_db_pool is None:
    del sys.modules["db_pool"]
else:
    sys.modules["db_pool"] = _prev_db_pool


class _FakeCursor:
    def __init__(self, rowcounts):
        self.rowcounts = rowcounts
        self.rowcount = 0
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        insight_type = params[1]
        self.rowcount = self.rowcounts.get(insight_type, 0)


class _FakeConn:
    def __init__(self, rowcounts):
        self._cursor = _FakeCursor(rowcounts)
        self.commit_count = 0

    def cursor(self, cursor_factory=None):  # noqa: ARG002
        return self._cursor

    def commit(self):
        self.commit_count += 1


def test_auto_resolve_health_insights_emits_recovery_event(monkeypatch):
    conn = _FakeConn(
        {
            "health_score_critical": 1,
            "health_score_low": 1,
            "health_score_warning": 0,
        }
    )

    captured = {}

    event_bus_stub = types.ModuleType("event_bus")
    event_bus_stub.emit_event = lambda **kwargs: captured.update(kwargs)

    prev_event_bus = sys.modules.get("event_bus")
    sys.modules["event_bus"] = event_bus_stub
    try:
        resolved = thr._auto_resolve_health_score_insights(conn, "proj-1", 70)
    finally:
        if prev_event_bus is None:
            del sys.modules["event_bus"]
        else:
            sys.modules["event_bus"] = prev_event_bus

    assert conn.commit_count == 1
    assert set(resolved) == {"health_score_critical", "health_score_low"}
    assert captured["event_type"] == "health.score_recovered"
    assert captured["entity_id"] == "proj-1"


def test_auto_resolve_health_insights_skips_below_threshold(monkeypatch):
    _ = monkeypatch
    conn = _FakeConn(
        {
            "health_score_critical": 1,
            "health_score_low": 1,
            "health_score_warning": 1,
        }
    )

    resolved = thr._auto_resolve_health_score_insights(conn, "proj-2", 40)

    assert resolved == []
    assert conn.commit_count == 0
    assert conn._cursor.calls == []
