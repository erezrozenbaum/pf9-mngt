import os
import sys
import types


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# db_writer imports psycopg2 at module import time. Stub it so these logic-only
# tests can run in lightweight environments without DB drivers installed.
def _ensure_psycopg2_extras_symbols() -> None:
    try:
        from psycopg2.extras import execute_values, RealDictCursor  # type: ignore

        _ = (execute_values, RealDictCursor)
        return
    except Exception:
        pass

    psycopg2_mod = sys.modules.get("psycopg2")
    if psycopg2_mod is None:
        psycopg2_mod = types.ModuleType("psycopg2")
        sys.modules["psycopg2"] = psycopg2_mod

    extras_mod = sys.modules.get("psycopg2.extras")
    if extras_mod is None:
        extras_mod = getattr(psycopg2_mod, "extras", None)
    if extras_mod is None:
        extras_mod = types.ModuleType("psycopg2.extras")

    if not hasattr(extras_mod, "execute_values"):
        extras_mod.execute_values = lambda *args, **kwargs: None

    if not hasattr(extras_mod, "RealDictCursor"):
        class _RealDictCursor:  # pragma: no cover - import placeholder only
            pass

        extras_mod.RealDictCursor = _RealDictCursor

    psycopg2_mod.extras = extras_mod
    sys.modules["psycopg2.extras"] = extras_mod


_ensure_psycopg2_extras_symbols()

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
