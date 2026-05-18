"""v2.3.2 — Wave execution timeline and SLA migration tracking.

Adds started_at / completed_at timestamps to migration_waves and a
migrations_completed counter to sla_compliance_monthly.

Revision ID: v2_3_2_wave_timeline
Revises: v2_3_0_db_roles
Create Date: 2026-05-19 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "v2_3_2_wave_timeline"
down_revision: Union[str, None] = "v2_3_0_db_roles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    import os
    sql_file = os.path.join(
        os.path.dirname(__file__), "..", "..", "migrate_v2_3_2_wave_timeline.sql"
    )
    if os.path.exists(sql_file):
        with open(sql_file, "r") as f:
            sql = f.read()
        op.execute(sql)
    else:
        # Fallback: inline the critical DDL
        op.execute(
            "ALTER TABLE migration_waves "
            "ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ, "
            "ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ"
        )
        op.execute(
            "ALTER TABLE sla_compliance_monthly "
            "ADD COLUMN IF NOT EXISTS migrations_completed INTEGER NOT NULL DEFAULT 0"
        )


def downgrade() -> None:
    op.execute("ALTER TABLE migration_waves DROP COLUMN IF EXISTS started_at")
    op.execute("ALTER TABLE migration_waves DROP COLUMN IF EXISTS completed_at")
    op.execute(
        "ALTER TABLE sla_compliance_monthly DROP COLUMN IF EXISTS migrations_completed"
    )
