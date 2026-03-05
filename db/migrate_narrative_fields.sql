-- ============================================================
-- Migration: Add narrative (executive_summary, technical_notes)
-- to migration_projects for the Migration Plan PDF/UI
-- ============================================================

DO $$ BEGIN
    ALTER TABLE migration_projects ADD COLUMN executive_summary TEXT;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE migration_projects ADD COLUMN technical_notes TEXT;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;
