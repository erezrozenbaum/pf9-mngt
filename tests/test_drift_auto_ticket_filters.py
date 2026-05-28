import os
import sys
import types


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# db_writer imports psycopg2 at module import time. Stub it so these logic-only
# tests can run in lightweight environments without DB drivers installed.
if "psycopg2" not in sys.modules:
    psycopg2_stub = types.ModuleType("psycopg2")
    extras_stub = types.ModuleType("psycopg2.extras")
    extras_stub.execute_values = lambda *args, **kwargs: None

    class _RealDictCursor:  # pragma: no cover - placeholder for import only
        pass

    extras_stub.RealDictCursor = _RealDictCursor
    psycopg2_stub.extras = extras_stub
    sys.modules["psycopg2"] = psycopg2_stub
    sys.modules["psycopg2.extras"] = extras_stub

from db_writer import _is_expected_drift_change


def test_expected_snapshot_auto_deletion_is_suppressed():
    assert _is_expected_drift_change(
        severity="warning",
        resource_type="snapshots",
        field_changed="status",
        old_value="active",
        new_value="deleted",
        description="snapshot status changed",
        resource_name="auto-ORG1-daily-5-foo",
    ) is True


def test_manual_snapshot_deletion_not_suppressed_by_default():
    assert _is_expected_drift_change(
        severity="warning",
        resource_type="snapshots",
        field_changed="status",
        old_value="active",
        new_value="deleted",
        description="snapshot status changed",
        resource_name="manual-prod-snapshot-001",
    ) is False


def test_custom_ignore_rule_matches_when_all_conditions_satisfy():
    rules = [
        {
            "resource_type": "ports",
            "field_changed": "status",
            "old_value": "active",
            "new_value": "deleted",
            "description_contains": "deleted from OpenStack",
            "resource_name_regex": r"^temp-",
        }
    ]
    assert _is_expected_drift_change(
        severity="warning",
        resource_type="ports",
        field_changed="status",
        old_value="active",
        new_value="deleted",
        description="port 'temp-123' was deleted from OpenStack",
        resource_name="temp-123",
        ignore_rules=rules,
    ) is True


def test_custom_ignore_rule_does_not_match_when_regex_fails():
    rules = [
        {
            "resource_type": "ports",
            "field_changed": "status",
            "new_value": "deleted",
            "resource_name_regex": r"^temp-",
        }
    ]
    assert _is_expected_drift_change(
        severity="warning",
        resource_type="ports",
        field_changed="status",
        old_value="active",
        new_value="deleted",
        description="port was deleted",
        resource_name="core-port-1",
        ignore_rules=rules,
    ) is False
