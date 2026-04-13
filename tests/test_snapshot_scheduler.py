"""
tests/test_snapshot_scheduler.py — Unit tests for snapshot scheduling logic.

Tests cover:
  B12.2 — policy validators, compliance state determination (active/paused/
           expired/quota-exceeded), helper utilities.

No live DB or OpenStack access required.  DB-coupled routes are not imported;
only the pure helper functions and Pydantic models are tested directly.
"""
import os
import sys
import types
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

_API_DIR = os.path.join(os.path.dirname(__file__), "..", "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

# ---------------------------------------------------------------------------
# Stubs — must come before importing snapshot_management
# ---------------------------------------------------------------------------

# If an earlier test file registered a minimal pydantic stub (without ValidationInfo),
# remove it so snapshot_management gets the real pydantic v2.
if "pydantic" in sys.modules and not hasattr(sys.modules["pydantic"], "ValidationInfo"):
    sys.modules.pop("pydantic", None)
    sys.modules.pop("pydantic.v1", None)
    # Also evict snapshot_management if it was cached with the wrong pydantic
    sys.modules.pop("snapshot_management", None)

_db_pool_stub = types.ModuleType("db_pool")
_db_pool_stub.get_connection = MagicMock(side_effect=RuntimeError("no DB in tests"))
sys.modules.setdefault("db_pool", _db_pool_stub)

_auth_stub = types.ModuleType("auth")
_auth_stub.require_permission = lambda *a, **kw: (lambda f: f)
_auth_stub.get_current_user = MagicMock(return_value=None)
_auth_stub.User = MagicMock()
sys.modules.setdefault("auth", _auth_stub)

from snapshot_management import (   # noqa: E402
    _parse_policy_list,
    _safe_int,
    SnapshotPolicySetCreate,
    SnapshotAssignmentCreate,
    SnapshotExclusionCreate,
)


# ===========================================================================
# 1.  _parse_policy_list
# ===========================================================================

class TestParsePolicyList:
    def test_empty_string_returns_empty(self):
        assert _parse_policy_list("") == []

    def test_none_returns_empty(self):
        assert _parse_policy_list(None) == []

    def test_single_policy(self):
        assert _parse_policy_list("daily_5") == ["daily_5"]

    def test_comma_separated(self):
        assert _parse_policy_list("daily_5,weekly_4") == ["daily_5", "weekly_4"]

    def test_semicolon_as_separator(self):
        assert _parse_policy_list("daily_5;weekly_4") == ["daily_5", "weekly_4"]

    def test_whitespace_stripped(self):
        result = _parse_policy_list("  daily_5 , weekly_4 ")
        assert result == ["daily_5", "weekly_4"]

    def test_empty_segments_dropped(self):
        result = _parse_policy_list("daily_5,,weekly_4,")
        assert result == ["daily_5", "weekly_4"]

    def test_mixed_separators(self):
        result = _parse_policy_list("daily_5;weekly_4,monthly_1st")
        assert "daily_5" in result
        assert "weekly_4" in result
        assert "monthly_1st" in result


# ===========================================================================
# 2.  _safe_int
# ===========================================================================

class TestSafeInt:
    def test_none_returns_none(self):
        assert _safe_int(None) is None

    def test_integer_passthrough(self):
        assert _safe_int(7) == 7

    def test_string_integer(self):
        assert _safe_int("7") == 7

    def test_float_truncates(self):
        assert _safe_int(3.9) == 3

    def test_invalid_string_returns_none(self):
        assert _safe_int("abc") is None

    def test_zero_returns_zero(self):
        assert _safe_int(0) == 0

    def test_negative(self):
        assert _safe_int(-5) == -5

    def test_empty_string_returns_none(self):
        assert _safe_int("") is None


# ===========================================================================
# 3.  Pydantic validators: SnapshotPolicySetCreate
# ===========================================================================

class TestSnapshotPolicySetCreate:
    def test_valid_model(self):
        obj = SnapshotPolicySetCreate(
            name="Standard Policy",
            policies=["daily_5", "weekly_4"],
            retention_map={"daily_5": 5, "weekly_4": 4},
        )
        assert obj.name == "Standard Policy"
        assert len(obj.policies) == 2

    def test_missing_retention_key_raises(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            SnapshotPolicySetCreate(
                name="Bad Policy",
                policies=["daily_5", "weekly_4"],
                retention_map={"daily_5": 5},  # weekly_4 missing
            )

    def test_empty_policies_raises(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            SnapshotPolicySetCreate(
                name="Bad Policy",
                policies=[],
                retention_map={},
            )

    def test_single_policy_valid(self):
        obj = SnapshotPolicySetCreate(
            name="Single",
            policies=["daily_5"],
            retention_map={"daily_5": 5},
        )
        assert len(obj.policies) == 1

    def test_optional_description(self):
        obj = SnapshotPolicySetCreate(
            name="P",
            policies=["daily_5"],
            retention_map={"daily_5": 5},
            description="My policy",
        )
        assert obj.description == "My policy"

    def test_is_global_defaults_false(self):
        obj = SnapshotPolicySetCreate(
            name="P",
            policies=["daily_5"],
            retention_map={"daily_5": 5},
        )
        assert obj.is_global is False

    def test_priority_default_zero(self):
        obj = SnapshotPolicySetCreate(
            name="P",
            policies=["daily_5"],
            retention_map={"daily_5": 5},
        )
        assert obj.priority == 0


# ===========================================================================
# 4.  Pydantic validators: SnapshotAssignmentCreate
# ===========================================================================

class TestSnapshotAssignmentCreate:
    def test_valid_assignment(self):
        obj = SnapshotAssignmentCreate(
            volume_id="vol-001",
            tenant_id="tenant-001",
            project_id="proj-001",
            policies=["daily_5"],
            retention_map={"daily_5": 5},
        )
        assert obj.volume_id == "vol-001"
        assert obj.auto_snapshot is True

    def test_empty_policies_raises(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            SnapshotAssignmentCreate(
                volume_id="vol-001",
                tenant_id="tenant-001",
                project_id="proj-001",
                policies=[],
                retention_map={},
            )

    def test_multiple_policies_allowed(self):
        obj = SnapshotAssignmentCreate(
            volume_id="v",
            tenant_id="t",
            project_id="p",
            policies=["daily_5", "weekly_4", "monthly_1st"],
            retention_map={"daily_5": 5, "weekly_4": 4, "monthly_1st": 3},
        )
        assert len(obj.policies) == 3


# ===========================================================================
# 5.  Compliance state determination logic
#     Mirrors the inline state machine in _build_compliance_from_volumes()
# ===========================================================================

def _compliance_status(
    last_snapshot_at,
    days: int,
    volume_id: str,
    quota_blocked_volumes: set,
    policy_has_run: bool,
) -> str:
    """
    Replicates the compliance status state machine from snapshot_management.py
    so it can be tested in isolation without a DB cursor.
    """
    now = datetime.now(timezone.utc)
    if last_snapshot_at and last_snapshot_at >= (now - timedelta(days=days)):
        return "compliant"
    if volume_id in quota_blocked_volumes:
        return "quota_blocked"
    if not policy_has_run:
        return "pending"
    return "missing"


class TestComplianceStateMachine:
    def _now(self):
        return datetime.now(timezone.utc)

    # -- Active / compliant --------------------------------------------------

    def test_recent_snapshot_is_compliant(self):
        status = _compliance_status(
            last_snapshot_at=self._now() - timedelta(hours=12),
            days=1, volume_id="v1",
            quota_blocked_volumes=set(), policy_has_run=True,
        )
        assert status == "compliant"

    def test_snapshot_older_than_window_is_missing(self):
        status = _compliance_status(
            last_snapshot_at=self._now() - timedelta(days=3),
            days=1, volume_id="v1",
            quota_blocked_volumes=set(), policy_has_run=True,
        )
        assert status == "missing"

    def test_snapshot_exactly_at_boundary_is_compliant(self):
        # A snapshot taken exactly `days` ago (minus 1 second) should be compliant
        status = _compliance_status(
            last_snapshot_at=self._now() - timedelta(days=1, seconds=-1),
            days=1, volume_id="v1",
            quota_blocked_volumes=set(), policy_has_run=True,
        )
        assert status == "compliant"

    def test_snapshot_just_expired_is_missing(self):
        status = _compliance_status(
            last_snapshot_at=self._now() - timedelta(days=1, seconds=60),
            days=1, volume_id="v1",
            quota_blocked_volumes=set(), policy_has_run=True,
        )
        assert status == "missing"

    # -- Paused / policy never ran -------------------------------------------

    def test_no_snapshot_policy_never_ran_is_pending(self):
        status = _compliance_status(
            last_snapshot_at=None,
            days=1, volume_id="v1",
            quota_blocked_volumes=set(), policy_has_run=False,
        )
        assert status == "pending"

    def test_no_snapshot_policy_ran_is_missing(self):
        # Policy has run for other volumes but not this one
        status = _compliance_status(
            last_snapshot_at=None,
            days=1, volume_id="v1",
            quota_blocked_volumes=set(), policy_has_run=True,
        )
        assert status == "missing"

    # -- Quota blocked -------------------------------------------------------

    def test_quota_blocked_volume(self):
        status = _compliance_status(
            last_snapshot_at=None,
            days=1, volume_id="vol-blocked",
            quota_blocked_volumes={"vol-blocked"}, policy_has_run=True,
        )
        assert status == "quota_blocked"

    def test_quota_blocked_takes_priority_over_missing(self):
        # Old snapshot + quota blocked → quota_blocked wins
        status = _compliance_status(
            last_snapshot_at=self._now() - timedelta(days=10),
            days=1, volume_id="vol-blocked",
            quota_blocked_volumes={"vol-blocked"}, policy_has_run=True,
        )
        assert status == "quota_blocked"

    def test_quota_blocked_other_volume_not_affected(self):
        status = _compliance_status(
            last_snapshot_at=None,
            days=1, volume_id="vol-clean",
            quota_blocked_volumes={"vol-blocked"}, policy_has_run=True,
        )
        assert status == "missing"

    # -- Exclusion rules (boundary cases) ------------------------------------

    def test_weekly_window_compliant(self):
        # 7-day window; snapshot 5 days ago
        status = _compliance_status(
            last_snapshot_at=self._now() - timedelta(days=5),
            days=7, volume_id="v1",
            quota_blocked_volumes=set(), policy_has_run=True,
        )
        assert status == "compliant"

    def test_weekly_window_expired(self):
        status = _compliance_status(
            last_snapshot_at=self._now() - timedelta(days=8),
            days=7, volume_id="v1",
            quota_blocked_volumes=set(), policy_has_run=True,
        )
        assert status == "missing"

    # -- Priority ordering check (quota_blocked < missing < compliant < pending) --

    def test_status_sort_order_key(self):
        # Reproduces the status_order dict from snapshot_management.py
        status_order = {"quota_blocked": -1, "missing": 0, "compliant": 1, "pending": 2}
        statuses = ["compliant", "missing", "quota_blocked", "pending"]
        sorted_statuses = sorted(statuses, key=lambda s: status_order[s])
        assert sorted_statuses[0] == "quota_blocked"
        assert sorted_statuses[-1] == "pending"
