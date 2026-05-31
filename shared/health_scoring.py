"""Helpers for tenant health component scoring."""

from __future__ import annotations

from typing import Any


def compute_security_posture_component(
    *,
    mfa_enabled_users: int,
    mfa_total_users: int,
    exposed_vm_count: int,
    stale_vm_count: int,
    total_vm_count: int,
) -> dict[str, Any]:
    """
    Compute the security_posture health component (0-15).

    The component is built from three equal sub-checks (0-5 each):
      1) MFA coverage by project user population
      2) Exposed SSH/RDP footprint
      3) Image recency
    """
    mfa_total = max(0, int(mfa_total_users))
    mfa_enabled = max(0, int(mfa_enabled_users))
    exposed_vms = max(0, int(exposed_vm_count))
    stale_vms = max(0, int(stale_vm_count))
    total_vms = max(0, int(total_vm_count))

    if mfa_total > 0:
        mfa_coverage_pct = round((mfa_enabled / mfa_total) * 100.0, 1)
        mfa_sub = round((mfa_enabled / mfa_total) * 5)
    else:
        mfa_coverage_pct = 100.0
        mfa_sub = 5

    # Base at 100 and subtract 15 points for every exposed VM, then map 0-100 -> 0-5.
    exposure_score_100 = max(0.0, 100.0 - (15.0 * exposed_vms))
    exposure_sub = round(exposure_score_100 / 20.0)

    if total_vms > 0:
        stale_pct = (stale_vms / total_vms) * 100.0
    else:
        stale_pct = 0.0

    if stale_pct <= 0:
        os_sub = 5
    elif stale_pct >= 50.0:
        os_sub = 0
    else:
        os_sub = round((1.0 - (stale_pct / 50.0)) * 5)

    score = int(max(0, min(15, mfa_sub + exposure_sub + os_sub)))
    return {
        "score": score,
        "details": {
            "mfa_coverage_pct": mfa_coverage_pct,
            "mfa_enabled_users": mfa_enabled,
            "mfa_total_users": mfa_total,
            "exposed_vm_count": exposed_vms,
            "stale_vm_count": stale_vms,
            "total_vm_count": total_vms,
            "subscores": {
                "mfa_coverage": int(mfa_sub),
                "exposed_ports": int(exposure_sub),
                "os_recency": int(os_sub),
            },
        },
    }
