import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "intelligence_worker"))

from engines.sla_defense import SlaDefenseEngine, _urgency_factor, _threat_score, _threat_type_for_insight  # noqa: E402


class _FakeCursor:
    def __init__(self, fetchall_batches=None):
        self.fetchall_batches = list(fetchall_batches or [])
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        if self.fetchall_batches:
            return self.fetchall_batches.pop(0)
        return []


class _FakeConn:
    def __init__(self, fetchall_batches=None):
        self.cursor_obj = _FakeCursor(fetchall_batches=fetchall_batches)
        self.committed = False

    def cursor(self, cursor_factory=None):  # noqa: ARG002
        return self.cursor_obj

    def commit(self):
        self.committed = True


def test_urgency_factor_imminent_vs_buffer_vs_long_runway():
    assert _urgency_factor(0.05, 2) == 1.0
    assert _urgency_factor(0.20, 2) == 0.7
    assert _urgency_factor(10.0, 2) == 0.3
    assert _urgency_factor(30.0, 2) == 0.0


def test_threat_score_uses_confidence_and_urgency():
    # rto=4h => rto_days ~=0.166; runway below rto_days => urgency 1.0
    assert _threat_score(0.9, 0.1, 4) == 0.9
    # same confidence but low urgency bucket
    assert _threat_score(0.9, 10.0, 4) == 0.27


def test_threat_score_defaults_confidence_when_missing():
    assert _threat_score(None, 0.1, 4) == 0.6


def test_threat_type_mapping():
    assert _threat_type_for_insight("capacity_quota") == "capacity_runway"
    assert _threat_type_for_insight("anomaly_cpu") == "anomaly_cluster"
    assert _threat_type_for_insight("risk_health") == "health_decline"


def test_process_candidate_row_triggers_insert_and_marks_key():
    conn = _FakeConn()
    engine = SlaDefenseEngine(conn)
    triggered = set()

    fired = engine._process_candidate_row(
        {
            "project_id": "p1",
            "sla_id": 11,
            "insight_id": 22,
            "insight_type": "capacity_quota",
            "runway_days": 0.05,
            "confidence": 0.9,
            "rto_hours": 2,
            "project_name": "Project 1",
            "tier": "gold",
        },
        triggered,
    )

    assert fired is True
    assert ("p1", "capacity_runway") in triggered
    assert any("INSERT INTO sla_defense_alerts" in sql for sql, _ in conn.cursor_obj.executed)
    assert any("INSERT INTO operational_events" in sql for sql, _ in conn.cursor_obj.executed)


def test_run_resolves_stale_open_alerts():
    conn = _FakeConn(
        fetchall_batches=[
            [],
            [{"id": 5, "project_id": "p1", "threat_type": "capacity_runway"}],
        ]
    )
    engine = SlaDefenseEngine(conn)

    engine.run()

    assert conn.committed is True
    assert any("UPDATE sla_defense_alerts" in sql for sql, _ in conn.cursor_obj.executed)
