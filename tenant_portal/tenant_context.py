"""
tenant_context.py — Immutable context object attached to every authenticated request.

Every route handler that requires auth receives a TenantContext via the
get_tenant_context() FastAPI dependency. It carries the verified, decoded
token claims for the lifetime of the request.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class TenantContext:
    """Verified, immutable per-request tenant identity."""

    keystone_user_id: str
    username: str
    control_plane_id: str
    project_ids: List[str]  # noqa: RUF012
    region_ids: List[str]   # noqa: RUF012
    ip_address: str
    portal_role: str = "manager"  # 'manager' | 'observer'

    @property
    def project_ids_csv(self) -> str:
        """Comma-separated project_ids for PostgreSQL SET LOCAL."""
        return ",".join(self.project_ids)

    @property
    def region_ids_csv(self) -> str:
        """Comma-separated region_ids for PostgreSQL SET LOCAL."""
        return ",".join(self.region_ids)
