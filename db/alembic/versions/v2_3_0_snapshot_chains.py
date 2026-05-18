"""v2.3.0 — Snapshot chain tracking: parent linkage, depth, policies, pre-delete guard.

Revision ID: v2_3_0_snapshot_chains
Revises: v2_3_0_db_roles
Create Date: 2026-05-18 00:03:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "v2_3_0_snapshot_chains"
down_revision: Union[str, None] = "v2_3_0_db_roles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE snapshot_records
            ADD COLUMN IF NOT EXISTS parent_snapshot_id TEXT
                REFERENCES snapshot_records(snapshot_id) DEFERRABLE INITIALLY DEFERRED
        """
    )
    op.execute(
        "ALTER TABLE snapshot_records "
        "ADD COLUMN IF NOT EXISTS chain_depth INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE snapshot_records "
        "ADD COLUMN IF NOT EXISTS chain_root_snapshot_id TEXT"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_snapshot_records_parent "
        "ON snapshot_records(parent_snapshot_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_snapshot_records_chain_root "
        "ON snapshot_records(chain_root_snapshot_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshot_chain_policies (
            id              BIGSERIAL PRIMARY KEY,
            project_id      TEXT NOT NULL,
            volume_id       TEXT NOT NULL,
            max_chain_depth INTEGER NOT NULL DEFAULT 5,
            auto_rebase     BOOLEAN NOT NULL DEFAULT true,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (project_id, volume_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_snapshot_chain_policies_project "
        "ON snapshot_chain_policies(project_id)"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_snapshot_chain_break()
        RETURNS TRIGGER AS $$
        DECLARE child_count INTEGER;
        BEGIN
            SELECT COUNT(*) INTO child_count
              FROM snapshot_records
             WHERE parent_snapshot_id = OLD.snapshot_id
               AND status <> 'deleted' AND id <> OLD.id;
            IF child_count > 0 THEN
                RAISE EXCEPTION 'Cannot delete snapshot % — % child snapshot(s) still exist.',
                    OLD.snapshot_id, child_count USING ERRCODE = '23503';
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_prevent_snapshot_chain_break ON snapshot_records")
    op.execute(
        """
        CREATE TRIGGER trg_prevent_snapshot_chain_break
            BEFORE DELETE ON snapshot_records
            FOR EACH ROW EXECUTE FUNCTION prevent_snapshot_chain_break()
        """
    )
    op.execute(
        "INSERT INTO schema_migrations (filename, applied_at) "
        "VALUES ('migrate_v2_3_0_snapshot_chains.sql', NOW()) "
        "ON CONFLICT (filename) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_prevent_snapshot_chain_break ON snapshot_records")
    op.execute("DROP FUNCTION IF EXISTS prevent_snapshot_chain_break()")
    op.execute("DROP TABLE IF EXISTS snapshot_chain_policies")
    op.execute("DROP INDEX IF EXISTS idx_snapshot_records_chain_root")
    op.execute("DROP INDEX IF EXISTS idx_snapshot_records_parent")
    op.execute("ALTER TABLE snapshot_records DROP COLUMN IF EXISTS chain_root_snapshot_id")
    op.execute("ALTER TABLE snapshot_records DROP COLUMN IF EXISTS chain_depth")
    op.execute("ALTER TABLE snapshot_records DROP COLUMN IF EXISTS parent_snapshot_id")
    op.execute(
        "DELETE FROM schema_migrations WHERE filename = 'migrate_v2_3_0_snapshot_chains.sql'"
    )
