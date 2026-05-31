import asyncio
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

# Allow importing api modules as top-level modules.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

# Minimal stubs used during import.
auth_stub = types.ModuleType("auth")
auth_stub.require_permission = lambda *_args, **_kwargs: (lambda: {"username": "admin", "role": "admin"})
auth_stub.User = dict
auth_stub.create_access_token = lambda *args, **kwargs: "tok"

cache_stub = types.ModuleType("cache")
cache_stub._get_client = lambda: None

copilot_context_stub = types.ModuleType("copilot_context")
copilot_context_stub.build_infra_context = lambda redact=True: "CTX"

copilot_llm_stub = types.ModuleType("copilot_llm")
copilot_llm_stub.ask_llm = lambda *args, **kwargs: ("", "builtin", None, False)

_prev_auth = sys.modules.get("auth")
_prev_cache = sys.modules.get("cache")
_prev_ctx = sys.modules.get("copilot_context")
_prev_llm = sys.modules.get("copilot_llm")

sys.modules["auth"] = auth_stub
sys.modules["cache"] = cache_stub
sys.modules["copilot_context"] = copilot_context_stub
sys.modules["copilot_llm"] = copilot_llm_stub

import ai_triage  # noqa: E402
import ai_triage_routes as routes  # noqa: E402

if _prev_auth is None:
    del sys.modules["auth"]
else:
    sys.modules["auth"] = _prev_auth

if _prev_cache is None:
    del sys.modules["cache"]
else:
    sys.modules["cache"] = _prev_cache

if _prev_ctx is None:
    del sys.modules["copilot_context"]
else:
    sys.modules["copilot_context"] = _prev_ctx

if _prev_llm is None:
    del sys.modules["copilot_llm"]
else:
    sys.modules["copilot_llm"] = _prev_llm


class _FakeCursor:
    def __init__(self, script):
        self.script = script
        self._fetchone = None
        self._fetchall = []
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.script.append((sql, params))
        s = " ".join(sql.split())
        if "COUNT(*) FILTER" in s and "FROM incident_briefs" in s:
            self._fetchone = {"open": 2, "dismissed": 1, "executed": 3}
        elif "FROM incident_briefs" in s and "COUNT(*)" in s and "generated_at > NOW()" in s:
            self._fetchone = (0,)
        elif "INSERT INTO incident_briefs" in s:
            self._fetchone = {"id": 42, "generated_at": datetime.now(timezone.utc)}
        elif "FROM incident_briefs" in s and "ORDER BY b.generated_at DESC" in s:
            self._fetchall = [{"id": 1, "event_type": "x", "generated_at": datetime.now(timezone.utc)}]
        elif "UPDATE incident_briefs" in s:
            self.rowcount = 1
        elif "SELECT id, runbook_name, executed_runbook_id" in s:
            self._fetchone = {"id": 5, "runbook_name": "stuck_vm_reboot", "executed_runbook_id": None}
        elif "SELECT id FROM runbook_executions" in s:
            self._fetchone = {"id": 77}
        else:
            self._fetchone = None

    def fetchone(self):
        return self._fetchone

    def fetchall(self):
        return self._fetchall


class _FakeConn:
    def __init__(self, script):
        self.script = script
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, cursor_factory=None):  # noqa: ARG002
        return _FakeCursor(self.script)

    def commit(self):
        self.committed = True


def test_evaluate_ai_triage_skips_when_disabled(monkeypatch):
    monkeypatch.setattr(ai_triage, "_load_triage_runtime_config", lambda: {"ai_triage_enabled": False})
    called = {"n": 0}
    monkeypatch.setattr(ai_triage, "ask_llm", lambda *args, **kwargs: called.__setitem__("n", called["n"] + 1))

    out = ai_triage.evaluate_ai_triage(1, "x", "critical", "e", "p", "P", {})

    assert out is None
    assert called["n"] == 0


def test_evaluate_ai_triage_respects_rate_limit(monkeypatch):
    cfg = {
        "ai_triage_enabled": True,
        "ai_triage_min_severity": "critical",
        "ai_triage_max_per_hour": 1,
        "backend": "openai",
        "openai_api_key": "k",
        "openai_model": "m",
        "ollama_url": "",
        "ollama_model": "",
        "anthropic_api_key": "",
        "anthropic_model": "",
        "redact_sensitive": True,
        "ai_triage_notify_email": False,
    }
    monkeypatch.setattr(ai_triage, "_load_triage_runtime_config", lambda: cfg)

    script = []

    class _RateLimitedCursor(_FakeCursor):
        def execute(self, sql, params=None):
            self.script.append((sql, params))
            if "COUNT(*)" in sql and "incident_briefs" in sql:
                self._fetchone = (1,)

    class _RateLimitedConn(_FakeConn):
        def cursor(self, cursor_factory=None):  # noqa: ARG002
            return _RateLimitedCursor(self.script)

    monkeypatch.setattr(ai_triage, "get_connection", lambda: _RateLimitedConn(script))

    called = {"n": 0}
    monkeypatch.setattr(ai_triage, "ask_llm", lambda *args, **kwargs: called.__setitem__("n", called["n"] + 1))

    out = ai_triage.evaluate_ai_triage(1, "x", "critical", "e", "p", "P", {})

    assert out is None
    assert called["n"] == 0


def test_evaluate_ai_triage_stores_and_publishes_with_free_text_fallback(monkeypatch):
    cfg = {
        "ai_triage_enabled": True,
        "ai_triage_min_severity": "high",
        "ai_triage_max_per_hour": 10,
        "backend": "openai",
        "openai_api_key": "k",
        "openai_model": "m",
        "ollama_url": "",
        "ollama_model": "",
        "anthropic_api_key": "",
        "anthropic_model": "",
        "redact_sensitive": True,
        "ai_triage_notify_email": False,
    }
    monkeypatch.setattr(ai_triage, "_load_triage_runtime_config", lambda: cfg)
    monkeypatch.setattr(ai_triage, "build_infra_context", lambda redact=True: "CTX")
    monkeypatch.setattr(ai_triage, "ask_llm", lambda *args, **kwargs: ("plain text response", "openai", 11, True))

    script = []
    monkeypatch.setattr(ai_triage, "get_connection", lambda: _FakeConn(script))

    published = {}
    monkeypatch.setattr(ai_triage, "_publish_incident_brief", lambda payload: published.update(payload))
    monkeypatch.setattr(ai_triage, "_notify_via_email_if_enabled", lambda *_args, **_kwargs: None)

    out = ai_triage.evaluate_ai_triage(9, "anomaly.realtime", "critical", "vm-1", "p1", "Tenant A", {"x": 1})

    assert out == 42
    assert published.get("id") == 42
    assert published.get("event_id") == 9
    assert published.get("analysis") is not None


def test_briefs_summary_aggregates_counts(monkeypatch):
    script = []
    monkeypatch.setattr(routes, "get_connection", lambda: _FakeConn(script))

    out = routes.briefs_summary(hours=48, _user={"username": "admin"})

    assert out == {"open": 2, "dismissed": 1, "executed": 3, "total": 6}


def test_dismiss_marks_brief(monkeypatch):
    script = []
    conn = _FakeConn(script)
    monkeypatch.setattr(routes, "get_connection", lambda: conn)

    out = routes.dismiss_brief(3, routes.BriefDismissBody(note="done"), current_user={"username": "alice"})

    assert out["ok"] is True
    assert out["status"] == "dismissed"
    assert conn.committed is True


def test_execute_brief_sets_executed_runbook_id(monkeypatch):
    script = []
    conn = _FakeConn(script)
    monkeypatch.setattr(routes, "get_connection", lambda: conn)
    monkeypatch.setattr(routes, "create_access_token", lambda *args, **kwargs: "token")

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"execution_id": "exec-123", "status": "queued"}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            return _Resp()

    monkeypatch.setattr(routes.httpx, "AsyncClient", lambda timeout=30: _Client())

    out = asyncio.run(
        routes.execute_brief(
            5,
            routes.BriefExecuteBody(dry_run=True, parameters={}),
            request=None,
            current_user={"username": "alice", "role": "admin"},
        )
    )

    assert out["ok"] is True
    assert out["execution_id"] == "exec-123"
    assert out["runbook_execution_pk"] == 77
