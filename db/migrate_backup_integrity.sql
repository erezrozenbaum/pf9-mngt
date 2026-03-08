-- =====================================================================
-- Migration: Backup Integrity Validation columns (E5 — Phase E)
-- Adds integrity_status and integrity_checked_at to backup_history
-- =====================================================================

ALTER TABLE backup_history
    ADD COLUMN IF NOT EXISTS integrity_status     TEXT
        CHECK (integrity_status IN ('pending', 'valid', 'invalid', 'skipped')),
    ADD COLUMN IF NOT EXISTS integrity_checked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS integrity_notes      TEXT;
