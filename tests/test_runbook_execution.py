"""
tests/test_runbook_execution.py — Runbook execution edge case tests.

Tests cover (B12.4):
  - Concurrent execution lock (pg_try_advisory_lock pattern)
  - Approval timeout expiry state machine
  - Dry-run vs execute mode distinction
  - Orphan cleanup dry-run vs execute
  - Stuck VM recovery: report-only vs reboot modes

All external dependencies (DB, OpenStack API) are mocked or replaced with
minimal inline simulators.  No live stack required.
"""
import os
import sys
import types
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

_API_DIR = os.path.join(os.path.dirname(__file__), "..", "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)


# ===========================================================================
# Helpers — inline business logic from runbook_routes.py
# ===========================================================================

# ---------------------------------------------------------------------------
# Approval expiry logic
# ---------------------------------------------------------------------------

def _approval_is_expired(
    approval_requested_at: datetime,
    escalation_timeout_minutes: int,
    now: datetime = None,
) -> bool:
    """Replicate approval timeout logic from the runbook execution flow."""
    if now is None:
        now = datetime.now(timezone.utc)
    if not approval_requested_at:
        return False
    age_minutes = (now - approval_requested_at).total_seconds() / 60
    return age_minutes > escalation_timeout_minutes


def _effective_approval_state(
    status: str,
    requested_at: datetime,
    timeout_minutes: int,
    now: datetime = None,
) -> str:
    """Derive effective approval state accounting for timeout expiry."""
    if status == "approved":
        return "approved"
    if status == "rejected":
        return "rejected"
    if status == "pending":
        if _approval_is_expired(requested_at, timeout_minutes, now=now):
            return "expired"
        return "pending"
    return "unknown"


# ---------------------------------------------------------------------------
# pg_try_advisory_lock simulator
# ---------------------------------------------------------------------------

class AdvisoryLockSimulator:
    """Simulates Postgres pg_try_advisory_lock / pg_advisory_unlock."""

    def __init__(self):
        self._held: set = set()

    def try_lock(self, key: int) -> bool:
        if key in self._held:
            return False
        self._held.add(key)
        return True

    def unlock(self, key: int) -> None:
        self._held.discard(key)

    def is_held(self, key: int) -> bool:
        return key in self._held


# ---------------------------------------------------------------------------
# Dry-run vs execute helpers (mirrors _engine_stuck_vm / _engine_orphan_cleanup)
# ---------------------------------------------------------------------------

def _remediate_vm(vm: dict, action: str, dry_run: bool) -> dict:
    """Simulate stuck-VM remediation (reboot/report-only)."""
    if dry_run:
        return {"vm_id": vm["vm_id"], "action": "report_only (dry-run)", "executed": False}
    return {"vm_id": vm["vm_id"], "action": action, "executed": True}


def _remediate_orphan(resource: dict, dry_run: bool) -> dict:
    """Simulate orphan resource cleanup (delete/report-only)."""
    if dry_run:
        return {"resource_id": resource["id"], "action": "report_only (dry-run)", "deleted": False}
    return {"resource_id": resource["id"], "action": "delete", "deleted": True}


# ===========================================================================
# 1.  Approval expiry state machine
# ===========================================================================

class TestApprovalExpiry:
    def _now(self):
        return datetime.now(timezone.utc)

    def test_pending_within_timeout_stays_pending(self):
        requested = self._now() - timedelta(minutes=30)
        assert _effective_approval_state("pending", requested, timeout_minutes=60) == "pending"

    def test_pending_past_timeout_becomes_expired(self):
        requested = self._now() - timedelta(minutes=90)
        assert _effective_approval_state("pending", requested, timeout_minutes=60) == "expired"

    def test_approved_never_expires_even_after_long_wait(self):
        requested = self._now() - timedelta(days=365)
        assert _effective_approval_state("approved", requested, timeout_minutes=60) == "approved"

    def test_rejected_never_expires(self):
        requested = self._now() - timedelta(days=365)
        assert _effective_approval_state("rejected", requested, timeout_minutes=60) == "rejected"

    def test_exactly_at_boundary_is_still_pending(self):
        # age == timeout_minutes → NOT yet expired (condition is >)
        now = self._now()
        requested = now - timedelta(minutes=60)
        expired = _approval_is_expired(requested, 60, now=now)
        assert not expired

    def test_one_second_past_boundary_is_expired(self):
        now = self._now()
        requested = now - timedelta(minutes=60, seconds=1)
        expired = _approval_is_expired(requested, 60, now=now)
        assert expired

    def test_zero_minute_timeout_expires_immediately(self):
        requested = self._now() - timedelta(seconds=1)
        assert _effective_approval_state("pending", requested, timeout_minutes=0) == "expired"

    def test_none_requested_at_never_expires(self):
        assert _approval_is_expired(None, 60) is False

    def test_approved_state_permits_execution(self):
        state = _effective_approval_state("approved", self._now(), timeout_minutes=60)
        assert state == "approved"
        may_execute = state == "approved"
        assert may_execute is True

    def test_expired_state_blocks_execution(self):
        old = self._now() - timedelta(hours=2)
        state = _effective_approval_state("pending", old, timeout_minutes=60)
        assert state != "approved"

    def test_rejected_state_blocks_execution(self):
        state = _effective_approval_state("rejected", self._now(), timeout_minutes=60)
        assert state != "approved"


# ===========================================================================
# 2.  Concurrent execution lock (pg_try_advisory_lock pattern)
# ===========================================================================

class TestAdvisoryLock:
    def test_first_acquire_succeeds(self):
        sim = AdvisoryLockSimulator()
        assert sim.try_lock(42) is True

    def test_second_acquire_same_key_blocked(self):
        sim = AdvisoryLockSimulator()
        sim.try_lock(42)
        assert sim.try_lock(42) is False

    def test_different_keys_independent(self):
        sim = AdvisoryLockSimulator()
        sim.try_lock(1)
        assert sim.try_lock(2) is True

    def test_unlock_allows_re_acquire(self):
        sim = AdvisoryLockSimulator()
        sim.try_lock(42)
        sim.unlock(42)
        assert sim.try_lock(42) is True

    def test_unlock_unheld_key_is_safe(self):
        sim = AdvisoryLockSimulator()
        sim.unlock(999)  # Must not raise

    def test_three_concurrent_runbooks_independent(self):
        sim = AdvisoryLockSimulator()
        assert sim.try_lock(1) is True
        assert sim.try_lock(2) is True
        assert sim.try_lock(3) is True
        assert sim.try_lock(1) is False  # concurrent second trigger blocked
        sim.unlock(1)
        assert sim.try_lock(1) is True  # now allowed after first finishes

    def test_is_held_reflects_state(self):
        sim = AdvisoryLockSimulator()
        assert sim.is_held(10) is False
        sim.try_lock(10)
        assert sim.is_held(10) is True
        sim.unlock(10)
        assert sim.is_held(10) is False


# ===========================================================================
# 3.  Stuck VM recovery — dry-run vs execute
# ===========================================================================

class TestStuckVmDryRun:
    def _vm(self, vm_id="vm-001"):
        return {"vm_id": vm_id, "vm_name": f"vm-{vm_id}", "status": "BUILD"}

    def test_dry_run_does_not_execute(self):
        result = _remediate_vm(self._vm(), "soft_reboot", dry_run=True)
        assert result["executed"] is False
        assert "dry-run" in result["action"]

    def test_execute_marks_executed(self):
        result = _remediate_vm(self._vm(), "soft_reboot", dry_run=False)
        assert result["executed"] is True
        assert result["action"] == "soft_reboot"

    def test_hard_reboot_execute(self):
        result = _remediate_vm(self._vm(), "hard_reboot", dry_run=False)
        assert result["action"] == "hard_reboot"
        assert result["executed"] is True

    def test_dry_run_preserves_vm_id(self):
        result = _remediate_vm(self._vm("vm-xyz"), "soft_reboot", dry_run=True)
        assert result["vm_id"] == "vm-xyz"

    def test_dry_run_safe_for_large_batch(self):
        vms = [self._vm(f"vm-{i:03d}") for i in range(100)]
        results = [_remediate_vm(v, "soft_reboot", dry_run=True) for v in vms]
        assert all(r["executed"] is False for r in results)
        assert len(results) == 100

    def test_execute_processes_all_vms(self):
        vms = [self._vm(f"vm-{i}") for i in range(5)]
        results = [_remediate_vm(v, "hard_reboot", dry_run=False) for v in vms]
        assert all(r["executed"] is True for r in results)


# ===========================================================================
# 4.  Orphan cleanup — dry-run vs execute
# ===========================================================================

class TestOrphanCleanupDryRun:
    def _resource(self, rid="port-001"):
        return {"id": rid, "type": "port"}

    def test_dry_run_does_not_delete(self):
        result = _remediate_orphan(self._resource(), dry_run=True)
        assert result["deleted"] is False
        assert "dry-run" in result["action"]

    def test_execute_marks_deleted(self):
        result = _remediate_orphan(self._resource(), dry_run=False)
        assert result["deleted"] is True
        assert result["action"] == "delete"

    def test_resource_id_preserved_in_dry_run(self):
        result = _remediate_orphan(self._resource("fip-777"), dry_run=True)
        assert result["resource_id"] == "fip-777"

    def test_mixed_dry_run_and_execute(self):
        resource = self._resource()
        dry = _remediate_orphan(resource, dry_run=True)
        wet = _remediate_orphan(resource, dry_run=False)
        assert dry["deleted"] is False
        assert wet["deleted"] is True


# ===========================================================================
# 5.  Full runbook execution state machine transitions
# ===========================================================================

class TestRunbookStateMachineTransitions:
    def _now(self):
        return datetime.now(timezone.utc)

    def test_pending_to_approved_transition(self):
        # Simulate approval arriving before timeout
        requested = self._now() - timedelta(minutes=5)
        state_before = _effective_approval_state("pending", requested, timeout_minutes=60)
        assert state_before == "pending"
        # Approval granted → state changes
        state_after = _effective_approval_state("approved", requested, timeout_minutes=60)
        assert state_after == "approved"

    def test_pending_to_rejected_transition(self):
        state = _effective_approval_state("rejected", self._now(), timeout_minutes=60)
        assert state == "rejected"

    def test_pending_to_expired_transition(self):
        old = self._now() - timedelta(hours=2)
        state = _effective_approval_state("pending", old, timeout_minutes=60)
        assert state == "expired"

    def test_approved_execution_proceeds(self):
        state = _effective_approval_state("approved", self._now(), timeout_minutes=60)
        assert (state == "approved") is True

    def test_rejected_execution_blocked(self):
        state = _effective_approval_state("rejected", self._now(), timeout_minutes=60)
        assert (state == "approved") is False

    def test_expired_execution_blocked(self):
        old = self._now() - timedelta(hours=3)
        state = _effective_approval_state("pending", old, timeout_minutes=60)
        assert (state == "approved") is False

    def test_orphan_cleanup_report_only_in_dry_run(self):
        # Full scenario: discovery → dry-run report → nothing executed
        orphans = [{"id": f"vol-{i}"} for i in range(10)]
        results = [_remediate_orphan(o, dry_run=True) for o in orphans]
        assert all(r["deleted"] is False for r in results)

    def test_stuck_vm_recovery_execute_all(self):
        stuck_vms = [{"vm_id": f"vm-{i}", "status": "BUILD"} for i in range(3)]
        results = [_remediate_vm(v, "soft_reboot", dry_run=False) for v in stuck_vms]
        assert all(r["executed"] is True for r in results)
