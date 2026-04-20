"""
intelligence_utils.py
=====================
Shared utility module for the Operational Intelligence subsystem.

Single source of truth for insight-type → department routing.
Used by:
  - intelligence_routes.py  (?department= query filter)
  - copilot_intents.py      (Copilot workspace context)
  - Any future Phase 2+ consumer (recommendations, auto-ticket)

Adding a new insight type:  add ONE entry to _DEPT_MAP.  Nothing else changes.
"""
from __future__ import annotations

from typing import List, Optional

# ---------------------------------------------------------------------------
# Department mapping
# ---------------------------------------------------------------------------

_DEPT_MAP: dict[str, list[str]] = {
    # Support workspace — customer-facing issues, config drift, incidents
    "drift":        ["support"],
    "snapshot":     ["support"],
    "incident":     ["support"],
    # Engineering workspace — resource health, capacity, efficiency
    "capacity":          ["engineering"],
    "capacity_storage":  ["engineering"],
    "capacity_compute":  ["engineering"],
    "capacity_quota":    ["engineering"],
    "waste":             ["engineering"],
    "anomaly":           ["engineering"],
    "cross_region":      ["engineering"],
    # Operations workspace — risk + health score monitoring
    "risk":         ["operations", "support"],   # critical risk → both teams
    "health":       ["operations"],
    # SLA risk → operations (breach management) + support (client-facing escalation)
    "sla_risk":     ["operations", "support"],
}

VALID_DEPARTMENTS: frozenset[str] = frozenset({"support", "engineering", "operations", "general"})


def map_insight_to_departments(insight_type: str) -> List[str]:
    """Return departments that should see this insight type.

    Falls back to ['general'] so unknown types are never silently dropped.
    """
    return _DEPT_MAP.get(insight_type, ["general"])


def types_for_department(department: Optional[str]) -> Optional[List[str]]:
    """Given a ?department= query param value, return matching insight types.

    Returns None when department is None or 'general' — meaning no type filter
    should be applied (full global feed).

    Includes prefix-match expansion so that e.g. "anomaly" in the map also
    covers DB types like "anomaly_snapshot_spike", "anomaly_vm_spike", etc.
    """
    if not department or department == "general":
        return None
    base_types = [t for t, depts in _DEPT_MAP.items() if department in depts]
    return base_types
