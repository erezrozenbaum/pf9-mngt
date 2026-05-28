import sys
from pathlib import Path

# Allow importing api modules as top-level modules.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import event_bus  # noqa: E402


def test_quick_anomaly_skips_for_unsupported_event(monkeypatch):
    monkeypatch.setattr(event_bus, "_REALTIME_ANOMALY_ENABLED", True)

    called = {"upsert": 0, "emit": 0}

    monkeypatch.setattr(
        event_bus,
        "_upsert_realtime_anomaly_insight",
        lambda **_kwargs: called.__setitem__("upsert", called["upsert"] + 1) or True,
    )
    monkeypatch.setattr(
        event_bus,
        "emit_event",
        lambda **_kwargs: called.__setitem__("emit", called["emit"] + 1),
    )

    event_bus._quick_anomaly_check(
        event_type="vm.created",
        entity_type="server",
        entity_id="vm-1",
        entity_name="vm-1",
        project_id="p1",
        project_name="Project 1",
        metadata={"metric_value": 95},
    )

    assert called["upsert"] == 0
    assert called["emit"] == 0


def test_quick_anomaly_cache_miss_skips(monkeypatch):
    monkeypatch.setattr(event_bus, "_REALTIME_ANOMALY_ENABLED", True)
    monkeypatch.setattr(event_bus, "_get_realtime_stats", lambda *_args, **_kwargs: None)

    called = {"upsert": 0, "emit": 0}
    monkeypatch.setattr(
        event_bus,
        "_upsert_realtime_anomaly_insight",
        lambda **_kwargs: called.__setitem__("upsert", called["upsert"] + 1) or True,
    )
    monkeypatch.setattr(
        event_bus,
        "emit_event",
        lambda **_kwargs: called.__setitem__("emit", called["emit"] + 1),
    )

    event_bus._quick_anomaly_check(
        event_type="vm.cpu_spike",
        entity_type="server",
        entity_id="vm-1",
        entity_name="vm-1",
        project_id="p1",
        project_name="Project 1",
        metadata={"metric_value": 95},
    )

    assert called["upsert"] == 0
    assert called["emit"] == 0


def test_quick_anomaly_detects_and_emits(monkeypatch):
    monkeypatch.setattr(event_bus, "_REALTIME_ANOMALY_ENABLED", True)
    monkeypatch.setattr(event_bus, "_get_realtime_stats", lambda *_args, **_kwargs: {"mean": 50.0, "stddev": 5.0})

    captured = {"upsert": None, "emit": None}

    def _fake_upsert(**kwargs):
        captured["upsert"] = kwargs
        return True

    def _fake_emit(**kwargs):
        captured["emit"] = kwargs

    monkeypatch.setattr(event_bus, "_upsert_realtime_anomaly_insight", _fake_upsert)
    monkeypatch.setattr(event_bus, "emit_event", _fake_emit)

    event_bus._quick_anomaly_check(
        event_type="vm.cpu_spike",
        entity_type="server",
        entity_id="vm-1",
        entity_name="vm-1",
        project_id="p1",
        project_name="Project 1",
        metadata={"metric_value": 95},
    )

    assert captured["upsert"] is not None
    assert captured["upsert"]["insight_type"] == "anomaly_realtime_vm_cpu_spike"
    assert captured["upsert"]["severity"] in ("high", "critical")
    assert captured["emit"] is not None
    assert captured["emit"]["event_type"] == "anomaly.realtime"


def test_quick_anomaly_below_threshold_skips(monkeypatch):
    monkeypatch.setattr(event_bus, "_REALTIME_ANOMALY_ENABLED", True)
    monkeypatch.setattr(event_bus, "_get_realtime_stats", lambda *_args, **_kwargs: {"mean": 50.0, "stddev": 10.0})

    called = {"upsert": 0, "emit": 0}

    monkeypatch.setattr(
        event_bus,
        "_upsert_realtime_anomaly_insight",
        lambda **_kwargs: called.__setitem__("upsert", called["upsert"] + 1) or True,
    )
    monkeypatch.setattr(
        event_bus,
        "emit_event",
        lambda **_kwargs: called.__setitem__("emit", called["emit"] + 1),
    )

    event_bus._quick_anomaly_check(
        event_type="vm.ram_spike",
        entity_type="server",
        entity_id="vm-1",
        entity_name="vm-1",
        project_id="p1",
        project_name="Project 1",
        metadata={"metric_value": 55},
    )

    assert called["upsert"] == 0
    assert called["emit"] == 0
