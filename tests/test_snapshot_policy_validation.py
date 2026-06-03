"""
Regression tests for snapshot policy scope and retention consistency validation.
"""

import os
import sys
import types
from unittest.mock import MagicMock

import pytest

_API_DIR = os.path.join(os.path.dirname(__file__), "..", "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

_db_pool_stub = types.ModuleType("db_pool")
_db_pool_stub.get_connection = MagicMock(side_effect=RuntimeError("no DB in tests"))
sys.modules.setdefault("db_pool", _db_pool_stub)

_auth_stub = types.ModuleType("auth")
_auth_stub.require_permission = lambda *a, **kw: (lambda f: f)
_auth_stub.get_current_user = MagicMock(return_value=None)
_auth_stub.User = MagicMock()
sys.modules.setdefault("auth", _auth_stub)

from snapshot_management import (  # noqa: E402
    SnapshotPolicySetCreate,
    _validate_policy_consistency,
)


def test_non_global_policy_requires_tenant_id():
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        SnapshotPolicySetCreate(
            name="Tenant Policy",
            is_global=False,
            tenant_id=None,
            policies=["daily_5"],
            retention_map={"daily_5": 5},
        )


def test_retention_map_rejects_unknown_policy_keys():
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        SnapshotPolicySetCreate(
            name="Bad Retention",
            is_global=True,
            policies=["daily_5"],
            retention_map={"daily_5": 5, "monthly_1st": 1},
        )


def test_policy_consistency_helper_rejects_missing_retention_key():
    with pytest.raises(ValueError):
        _validate_policy_consistency(
            is_global=True,
            tenant_id="",
            policies=["daily_5", "monthly_1st"],
            retention_map={"daily_5": 5},
        )


def test_policy_consistency_helper_accepts_valid_payload():
    _validate_policy_consistency(
        is_global=False,
        tenant_id="tenant-123",
        policies=["daily_5", "monthly_1st"],
        retention_map={"daily_5": 5, "monthly_1st": 1},
    )
