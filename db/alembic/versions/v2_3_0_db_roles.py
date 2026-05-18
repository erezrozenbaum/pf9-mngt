"""v2.3.0 — Per-service PostgreSQL roles with least-privilege grants.

Creates dedicated NOLOGIN roles for each worker service. Operators
enable them by granting LOGIN + setting passwords, then updating the
per-service DB credential env vars in the deployment configuration.

Revision ID: v2_3_0_db_roles
Revises: v2_3_0_health_score_config
Create Date: 2026-05-18 00:02:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "v2_3_0_db_roles"
down_revision: Union[str, None] = "v2_3_0_health_score_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROLES = [
    "pf9_service_base",
    "pf9_snapshot_svc",
    "pf9_scheduler_svc",
    "pf9_notification_svc",
    "pf9_metering_svc",
    "pf9_intelligence_svc",
    "pf9_backup_svc",
    "pf9_ldap_svc",
]


def _role_exists(role: str) -> bool:
    from sqlalchemy import text
    conn = op.get_bind()
    result = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
    return result.fetchone() is not None


def upgrade() -> None:
    # Execute the full SQL migration script via file read
    import os
    sql_file = os.path.join(
        os.path.dirname(__file__), "..", "..", "migrate_v2_3_0_db_roles.sql"
    )
    if os.path.exists(sql_file):
        with open(sql_file, "r") as f:
            sql = f.read()
        op.execute(sql)
    else:
        # Fallback: inline the critical DDL
        for role in _ROLES:
            op.execute(
                f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') "
                f"THEN CREATE ROLE {role} NOLOGIN; END IF; END $$"
            )
        op.execute("GRANT USAGE ON SCHEMA public TO pf9_service_base")
        op.execute(
            "INSERT INTO schema_migrations (filename, applied_at) "
            "VALUES ('migrate_v2_3_0_db_roles.sql', NOW()) ON CONFLICT (filename) DO NOTHING"
        )


def downgrade() -> None:
    for role in reversed(_ROLES):
        op.execute(f"DROP ROLE IF EXISTS {role}")
    op.execute(
        "DELETE FROM schema_migrations WHERE filename = 'migrate_v2_3_0_db_roles.sql'"
    )
