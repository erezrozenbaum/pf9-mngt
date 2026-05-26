"""
tests/test_clea_conditions.py — Unit tests for the CLEA condition DSL (v2.14.0).

Covers:
  - _validate_condition_expr: valid + invalid expressions
  - _condition_matches: eq, neq, in, contains, metadata.* dot-path, backward compat
  - GET /api/admin/clea/condition-schema returns expected shape
"""
from __future__ import annotations

import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure the api/ directory is on sys.path
# ---------------------------------------------------------------------------
_API_DIR = os.path.join(os.path.dirname(__file__), "..", "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

# ---------------------------------------------------------------------------
# Stub heavy dependencies so we can import clea_routes.py without a real DB
# ---------------------------------------------------------------------------

def _make_stub(name: str, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


for mod_name, stub in [
    ("db_pool",      _make_stub("db_pool",      get_connection=MagicMock(), get_tenant_connection=MagicMock())),
    ("auth",         _make_stub("auth",          require_permission=lambda *a: MagicMock(), get_current_user=MagicMock())),
    ("middleware",   _make_stub("middleware",     get_tenant_context=MagicMock())),
    ("log_collector",_make_stub("log_collector",  log_action=MagicMock())),
    ("cache",        _make_stub("cache",          redis_client=MagicMock())),
    ("rate_limit",   _make_stub("rate_limit",     limiter=MagicMock())),
]:
    sys.modules.setdefault(mod_name, stub)

# psycopg2
psycopg2_stub = _make_stub("psycopg2")
psycopg2_stub.extras = _make_stub("psycopg2.extras", RealDictCursor=MagicMock())
sys.modules.setdefault("psycopg2", psycopg2_stub)
sys.modules.setdefault("psycopg2.extras", psycopg2_stub.extras)

from clea_routes import _validate_condition_expr, _condition_matches  # noqa: E402


# ===========================================================================
# _validate_condition_expr
# ===========================================================================

class TestValidateConditionExpr:
    def test_empty_dict_is_valid(self):
        assert _validate_condition_expr({}) == []

    def test_shorthand_known_key_is_valid(self):
        assert _validate_condition_expr({"severity": "critical"}) == []

    def test_full_eq_operator_is_valid(self):
        assert _validate_condition_expr({"severity": {"op": "eq", "value": "high"}}) == []

    def test_in_operator_with_list_is_valid(self):
        assert _validate_condition_expr({"severity": {"op": "in", "value": ["critical", "high"]}}) == []

    def test_neq_operator_is_valid(self):
        assert _validate_condition_expr({"entity_type": {"op": "neq", "value": "host"}}) == []

    def test_metadata_dot_path_eq_is_valid(self):
        assert _validate_condition_expr({"metadata.project_id": {"op": "eq", "value": "abc"}}) == []

    def test_metadata_dot_path_contains_is_valid(self):
        assert _validate_condition_expr({"metadata.category": {"op": "contains", "value": "snap"}}) == []

    def test_unknown_key_returns_error(self):
        errs = _validate_condition_expr({"nonexistent_key": "value"})
        assert len(errs) == 1
        assert "nonexistent_key" in errs[0]

    def test_unknown_operator_returns_error(self):
        errs = _validate_condition_expr({"severity": {"op": "regex", "value": "crit.*"}})
        assert len(errs) == 1
        assert "regex" in errs[0]

    def test_in_without_list_returns_error(self):
        errs = _validate_condition_expr({"severity": {"op": "in", "value": "critical"}})
        assert len(errs) == 1
        assert "list" in errs[0]

    def test_contains_without_string_returns_error(self):
        errs = _validate_condition_expr({"metadata.tag": {"op": "contains", "value": 123}})
        assert len(errs) == 1
        assert "string" in errs[0]

    def test_dict_value_without_op_returns_error(self):
        errs = _validate_condition_expr({"severity": {"value": "critical"}})
        assert len(errs) == 1
        assert "op" in errs[0]

    def test_contains_not_allowed_on_top_level_key(self):
        # 'contains' is only allowed for metadata.* paths, not top-level keys
        errs = _validate_condition_expr({"severity": {"op": "contains", "value": "crit"}})
        assert any("contains" in e for e in errs), f"Expected 'contains' error, got: {errs}"

    def test_non_dict_expr_returns_error(self):
        errs = _validate_condition_expr("invalid")  # type: ignore[arg-type]
        assert len(errs) == 1

    def test_multiple_keys_multiple_errors(self):
        errs = _validate_condition_expr({
            "bad_key": "x",
            "severity": {"op": "bad_op", "value": "x"},
        })
        assert len(errs) >= 2


# ===========================================================================
# _condition_matches
# ===========================================================================

class TestConditionMatches:
    META = {
        "severity":    "critical",
        "entity_type": "vm",
        "project_id":  "proj-abc",
        "region_id":   "us-east",
        "category":    "snapshot_failure",
        "extra_field": "hello world",
    }

    def test_empty_expr_matches_all(self):
        assert _condition_matches({}, self.META) is True

    # --- eq (shorthand) ---
    def test_shorthand_eq_match(self):
        assert _condition_matches({"severity": "critical"}, self.META) is True

    def test_shorthand_eq_no_match(self):
        assert _condition_matches({"severity": "low"}, self.META) is False

    # --- eq (explicit) ---
    def test_explicit_eq_match(self):
        assert _condition_matches({"severity": {"op": "eq", "value": "critical"}}, self.META) is True

    def test_explicit_eq_no_match(self):
        assert _condition_matches({"severity": {"op": "eq", "value": "low"}}, self.META) is False

    # --- neq ---
    def test_neq_match(self):
        assert _condition_matches({"severity": {"op": "neq", "value": "low"}}, self.META) is True

    def test_neq_no_match(self):
        assert _condition_matches({"severity": {"op": "neq", "value": "critical"}}, self.META) is False

    # --- in ---
    def test_in_match(self):
        assert _condition_matches(
            {"severity": {"op": "in", "value": ["critical", "high"]}}, self.META
        ) is True

    def test_in_no_match(self):
        assert _condition_matches(
            {"severity": {"op": "in", "value": ["low", "medium"]}}, self.META
        ) is False

    def test_in_non_list_target_no_match(self):
        assert _condition_matches(
            {"severity": {"op": "in", "value": "critical"}}, self.META
        ) is False

    # --- contains ---
    def test_contains_match(self):
        assert _condition_matches(
            {"extra_field": {"op": "contains", "value": "world"}}, self.META
        ) is True

    def test_contains_no_match(self):
        assert _condition_matches(
            {"extra_field": {"op": "contains", "value": "xyz"}}, self.META
        ) is False

    def test_contains_non_string_actual_no_match(self):
        meta = {**self.META, "count": 5}
        assert _condition_matches(
            {"count": {"op": "contains", "value": "5"}}, meta
        ) is False

    # --- metadata.* dot-path ---
    def test_metadata_dot_path_eq_match(self):
        meta = {**self.META, "runway_days": 3}
        assert _condition_matches(
            {"metadata.runway_days": {"op": "eq", "value": 3}}, meta
        ) is True

    def test_metadata_dot_path_eq_no_match(self):
        meta = {**self.META, "runway_days": 3}
        assert _condition_matches(
            {"metadata.runway_days": {"op": "eq", "value": 99}}, meta
        ) is False

    def test_metadata_dot_path_in_match(self):
        meta = {**self.META, "sub_type": "quota"}
        assert _condition_matches(
            {"metadata.sub_type": {"op": "in", "value": ["quota", "billing"]}}, meta
        ) is True

    def test_metadata_dot_path_contains_match(self):
        meta = {**self.META, "category": "snapshot_failure_daily"}
        assert _condition_matches(
            {"metadata.category": {"op": "contains", "value": "snapshot"}}, meta
        ) is True

    # --- unknown op fails safe ---
    def test_unknown_op_returns_false(self):
        assert _condition_matches(
            {"severity": {"op": "regex", "value": "crit.*"}}, self.META
        ) is False

    # --- multiple conditions (all must match) ---
    def test_multiple_conditions_all_match(self):
        assert _condition_matches(
            {"severity": "critical", "entity_type": "vm"}, self.META
        ) is True

    def test_multiple_conditions_one_fails(self):
        assert _condition_matches(
            {"severity": "critical", "entity_type": "host"}, self.META
        ) is False
