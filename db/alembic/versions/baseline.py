"""Baseline revision — represents the full schema from db/init.sql plus all
   existing db/migrate_*.sql files applied up to and including v2.2.1.

   This revision performs no DDL changes. Its sole purpose is to establish
   Alembic's revision chain starting point so that future revisions can be
   created on top of it with a clear, auditable history.

   To baseline an existing database (only run once):
       alembic --config db/alembic.ini stamp baseline

   After that, run new migrations normally:
       alembic --config db/alembic.ini upgrade head

Revision ID: baseline
Revises:
Create Date: 2026-05-18 00:00:00.000000
"""
from typing import Sequence, Union

# revision identifiers
revision: str = "baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No DDL — this revision only marks the baseline schema as applied."""
    pass


def downgrade() -> None:
    """Cannot downgrade the baseline revision."""
    raise NotImplementedError(
        "The baseline revision cannot be reversed. "
        "If you need to reset the schema, recreate the database from db/init.sql."
    )
