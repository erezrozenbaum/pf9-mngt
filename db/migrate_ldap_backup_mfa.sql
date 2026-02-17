-- =====================================================================
-- MIGRATION: LDAP Backup support + MFA (TOTP) tables
-- Run once against an existing pf9_mgmt database.
-- Safe to re-run (uses IF NOT EXISTS / IF NOT EXISTS … DO).
-- =====================================================================

BEGIN;

-- 1. Add backup_target column to backup_history
--    Allows distinguishing database vs ldap backups.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'backup_history' AND column_name = 'backup_target'
    ) THEN
        ALTER TABLE backup_history
            ADD COLUMN backup_target TEXT NOT NULL DEFAULT 'database'
            CHECK (backup_target IN ('database', 'ldap'));
    END IF;
END $$;

-- 2. Add LDAP backup settings to backup_config
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'backup_config' AND column_name = 'ldap_backup_enabled'
    ) THEN
        ALTER TABLE backup_config
            ADD COLUMN ldap_backup_enabled BOOLEAN NOT NULL DEFAULT false;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'backup_config' AND column_name = 'ldap_retention_count'
    ) THEN
        ALTER TABLE backup_config
            ADD COLUMN ldap_retention_count INT NOT NULL DEFAULT 7 CHECK (ldap_retention_count >= 1);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'backup_config' AND column_name = 'ldap_retention_days'
    ) THEN
        ALTER TABLE backup_config
            ADD COLUMN ldap_retention_days INT NOT NULL DEFAULT 30 CHECK (ldap_retention_days >= 1);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'backup_config' AND column_name = 'last_ldap_backup_at'
    ) THEN
        ALTER TABLE backup_config
            ADD COLUMN last_ldap_backup_at TIMESTAMPTZ;
    END IF;
END $$;

-- 3. Index on backup_target for efficient filtering
CREATE INDEX IF NOT EXISTS idx_backup_history_target ON backup_history(backup_target);

-- =====================================================================
-- MFA / TOTP table
-- =====================================================================

CREATE TABLE IF NOT EXISTS user_mfa (
    id              SERIAL PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    totp_secret     TEXT NOT NULL,          -- base32-encoded TOTP secret (encrypted at rest recommended)
    is_enabled      BOOLEAN NOT NULL DEFAULT false,
    backup_codes    TEXT[],                 -- array of one-time backup codes (hashed)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_mfa_username ON user_mfa(username);

-- Add MFA permissions to role_permissions for admin & superadmin
INSERT INTO role_permissions (role, resource, action)
SELECT r, 'mfa', a
FROM (VALUES ('admin'), ('superadmin')) AS roles(r),
     (VALUES ('read'), ('write')) AS actions(a)
WHERE NOT EXISTS (
    SELECT 1 FROM role_permissions
    WHERE role = roles.r AND resource = 'mfa' AND action = actions.a
);

-- Viewers and operators can manage their own MFA (enforced in code)
-- but reading MFA status list is admin+

COMMIT;
