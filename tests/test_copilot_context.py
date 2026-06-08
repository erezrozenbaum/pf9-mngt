import sys
from pathlib import Path

# Allow importing api modules as top-level modules.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import copilot_context as cc  # noqa: E402


class _FakeCursor:
    def __init__(self):
        self._fetchone = None
        self._fetchall = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        _ = params
        s = " ".join(sql.split())
        self._fetchone = None
        self._fetchall = []

        if "(SELECT COUNT(*) FROM domains) AS domains" in s:
            self._fetchone = {
                "domains": 1,
                "projects": 2,
                "hosts": 3,
                "vms": 4,
                "volumes": 5,
                "networks": 6,
                "images": 7,
                "snapshots": 8,
            }
        elif "FROM hypervisors" in s and "SUM(vcpus) AS total_vcpus" in s:
            self._fetchone = {
                "total_vcpus": 100,
                "used_vcpus": 40,
                "total_mb": 102400,
                "used_mb": 51200,
                "total_gb": 1000,
                "used_gb": 320,
            }
        elif "FROM operational_insights" in s and "WHERE status = 'open'" in s:
            self._fetchall = [
                {
                    "severity": "critical",
                    "type": "capacity_quota",
                    "entity_name": "acme-prod",
                    "entity_id": "p-1",
                    "title": "Runway is low",
                    "metadata": {"runway_days": 6, "confidence": 0.82},
                }
            ]
        elif "FROM tenant_health_scores ths" in s and "ORDER BY ths.score ASC" in s:
            self._fetchall = [
                {
                    "project_id": "p-1",
                    "score": 42,
                    "project_name": "VerySecretProject",
                    "prev_score": 67,
                },
                {
                    "project_id": "p-2",
                    "score": 88,
                    "project_name": "StableTenant",
                    "prev_score": 89,
                },
            ]
        elif "FROM operational_insights" in s and "type LIKE 'anomaly%'" in s:
            self._fetchall = [
                {
                    "type": "anomaly_cpu",
                    "entity_name": "vm-critical-01",
                    "entity_id": "vm-1",
                    "severity": "high",
                }
            ]
        elif "FROM sla_commitments sc" in s and "oi.type LIKE 'capacity%'" in s:
            self._fetchall = [
                {
                    "project_name": "VerySecretProject",
                    "tier": "gold",
                    "insight_type": "capacity_quota",
                    "metadata": {"runway_days": 6},
                }
            ]
        elif "FROM clea_executions ce" in s and "JOIN clea_policies cp" in s:
            self._fetchall = [
                {
                    "approval_status": "pending",
                    "triggered_at": "2026-06-08T10:00:00Z",
                    "event_type": "quota.warning",
                    "runbook_name": "quota_threshold_check",
                    "project_name": "VerySecretProject",
                    "entity_name": "vm-critical-01",
                }
            ]
        elif "FROM hypervisors ORDER BY hostname" in s:
            self._fetchall = []
        elif "FROM servers s LEFT JOIN projects p" in s and "UPPER(s.status)" in s:
            self._fetchall = []
        elif "FROM drift_events" in s:
            self._fetchone = {"cnt": 0, "critical": 0}
        elif "FROM snapshots" in s:
            self._fetchone = {"total": 8, "available": 8}
        elif "FROM servers GROUP BY COALESCE(LOWER(os_distro), 'unknown')" in s:
            self._fetchall = [{"os": "ubuntu", "cnt": 4}]
        elif "FROM activity_log ORDER BY created_at DESC" in s:
            self._fetchall = []
        elif "FROM operational_events oe" in s:
            self._fetchall = []

    def fetchone(self):
        return self._fetchone

    def fetchall(self):
        return self._fetchall


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, cursor_factory=None):  # noqa: ARG002
        return _FakeCursor()


def test_build_infra_context_includes_g2_sections(monkeypatch):
    monkeypatch.setattr(cc, "get_connection", lambda: _FakeConn())

    text = cc.build_infra_context(redact=False)

    assert "OPEN INSIGHTS" in text
    assert "HEALTH SCORES (worst/declining)" in text
    assert "RECENT ANOMALIES (24h" in text
    assert "SLA AT RISK" in text
    assert "CLEA EXECUTIONS" in text
    assert "VerySecretProject" in text


def test_build_infra_context_redacts_project_names_in_g2_sections(monkeypatch):
    monkeypatch.setattr(cc, "get_connection", lambda: _FakeConn())

    text = cc.build_infra_context(redact=True)

    assert "VerySecretProject" not in text
    assert "Ver***" in text
    assert "acm***" in text
    assert "CLEA EXECUTIONS" in text
