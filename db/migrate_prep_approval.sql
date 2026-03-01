-- ============================================================
-- Phase 4B Prep Approval
-- Adds approval workflow columns to migration_projects and
-- creates the migration_prep_approvals audit table.
-- Safe to re-run (all statements are idempotent).
-- ============================================================

-- Add approval columns to migration_projects
DO $$ BEGIN
    ALTER TABLE migration_projects ADD COLUMN prep_approval_status TEXT;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE migration_projects ADD COLUMN prep_requested_by TEXT;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE migration_projects ADD COLUMN prep_approved_by TEXT;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE migration_projects ADD COLUMN prep_approved_at TIMESTAMPTZ;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

-- Approval history table
CREATE TABLE IF NOT EXISTS migration_prep_approvals (
    id          BIGSERIAL   PRIMARY KEY,
    project_id  TEXT        NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    approver    TEXT        NOT NULL,
    decision    TEXT        NOT NULL,   -- 'approved' | 'rejected'
    comment     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_prep_approvals_project
    ON migration_prep_approvals(project_id, created_at DESC);
