-- v1.93.21: Add SHA-256 integrity hash to backup_history (H7)
-- This column stores the hex-encoded SHA-256 checksum of each backup file,
-- computed immediately after the file is written by the backup worker.
-- The restore endpoint verifies the hash before allowing a restore.

ALTER TABLE backup_history
    ADD COLUMN IF NOT EXISTS integrity_hash VARCHAR(64);
