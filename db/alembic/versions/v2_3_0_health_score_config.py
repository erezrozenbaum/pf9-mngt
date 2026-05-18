"""v2.3.0 — health score configurable weights and per-tenant disable flag.

Revision ID: v2_3_0_health_score_config
Revises: baseline
Create Date: 2026-05-18 00:01:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "v2_3_0_health_score_config"
down_revision: Union[str, None] = "baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Configurable health score component weights stored in system_settings
    op.execute(
        """
        INSERT INTO system_settings (key, value, description) VALUES
            ('health_score.weight.snapshot_compliance', '25',
             'Points allocated to snapshot compliance component of tenant health score'),
            ('health_score.weight.quota_headroom',      '20',
             'Points allocated to quota headroom component of tenant health score'),
            ('health_score.weight.drift',               '20',
             'Points allocated to configuration drift component of tenant health score'),
            ('health_score.weight.sla_tier',            '20',
             'Points allocated to SLA tier component of tenant health score'),
            ('health_score.weight.tickets',             '15',
             'Points allocated to open support tickets component of tenant health score')
        ON CONFLICT (key) DO NOTHING
        """
    )
    # Per-tenant opt-out of health score computation
    op.execute(
        """
        ALTER TABLE projects
            ADD COLUMN IF NOT EXISTS health_score_disabled BOOLEAN NOT NULL DEFAULT false
        """
    )
    # Record migration in legacy tracking table (for run_migration.py compatibility)
    op.execute(
        """
        INSERT INTO schema_migrations (filename, applied_at)
        VALUES ('migrate_v2_3_0_health_score_config.sql', NOW())
        ON CONFLICT (filename) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM system_settings WHERE key LIKE 'health_score.weight.%'"
    )
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS health_score_disabled")
    op.execute(
        "DELETE FROM schema_migrations WHERE filename = 'migrate_v2_3_0_health_score_config.sql'"
    )
