import sys
import types
from pathlib import Path

# Allow importing api modules as top-level modules.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

auth_stub = types.ModuleType("auth")
auth_stub.require_permission = lambda *_args, **_kwargs: (lambda: {"username": "admin"})
auth_stub.User = dict

db_pool_stub = types.ModuleType("db_pool")
db_pool_stub.get_connection = lambda: None

_prev_auth = sys.modules.get("auth")
_prev_db_pool = sys.modules.get("db_pool")
sys.modules["auth"] = auth_stub
sys.modules["db_pool"] = db_pool_stub

import qbr_routes as qbr  # noqa: E402

if _prev_auth is None:
    del sys.modules["auth"]
else:
    sys.modules["auth"] = _prev_auth

if _prev_db_pool is None:
    del sys.modules["db_pool"]
else:
    sys.modules["db_pool"] = _prev_db_pool


class _FakeCursor:
    def __init__(self, script):
        self.script = script
        self._fetchone = None
        self._fetchall = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.script.append((sql, params))
        s = " ".join(sql.split())
        if "SELECT id, name FROM projects" in s:
            self._fetchone = {"id": "tenant-1", "name": "Tenant One"}
        elif "SELECT insight_type, hours_saved, rate_per_hour FROM msp_labor_rates" in s:
            self._fetchall = [{"insight_type": "ai_triage", "hours_saved": 1.0, "rate_per_hour": 100.0}]
        elif "COUNT(*)::int AS generated_count" in s:
            self._fetchone = {"generated_count": 3, "executed_count": 2}
        elif "FROM incident_briefs" in s and "executed_runbook_id IS NOT NULL" in s and "SELECT id, event_type" in s:
            self._fetchall = [
                {
                    "id": 9,
                    "event_type": "capacity.warning",
                    "runbook_name": "quota_expand",
                    "risk_level": "high",
                    "generated_at": None,
                }
            ]
        elif "FROM operational_insights" in s and "status = 'resolved'" in s:
            self._fetchall = []
        elif "FROM operational_insights" in s and "status IN ('open','acknowledged','snoozed')" in s:
            self._fetchall = []
        elif "FROM sla_commitments" in s:
            self._fetchone = None
        elif "information_schema.tables" in s and "migration_waves" in s:
            self._fetchone = (False,)
        else:
            self._fetchone = None
            self._fetchall = []

    def fetchone(self):
        return self._fetchone

    def fetchall(self):
        return self._fetchall


class _FakeConn:
    def __init__(self, script):
        self.script = script

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, cursor_factory=None):  # noqa: ARG002
        return _FakeCursor(self.script)


def test_qbr_includes_ai_triage_metrics_and_interventions(monkeypatch):
    script = []
    monkeypatch.setattr(qbr, "get_connection", lambda: _FakeConn(script))

    out = qbr._build_qbr_data("tenant-1", "2026-05-01", "2026-05-31", None)

    assert out["tenant_name"] == "Tenant One"
    assert out["ai_triage_count"] == 3
    assert out["ai_executed_count"] == 2
    assert any(i["type"] == "ai_triage" for i in out["interventions"])
    assert len(out["ai_triage_interventions"]) == 1
