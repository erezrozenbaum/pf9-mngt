-- =====================================================================
-- MIGRATION: External LDAP / AD Identity Federation Tables
-- Run this against existing databases to add LDAP sync support.
-- For fresh installs all tables are created via init.sql.
-- Safe to run multiple times — all statements use IF NOT EXISTS / DO NOTHING.
-- =====================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. ldap_sync_config  — one row per external LDAP/AD server
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ldap_sync_config (
    id                      SERIAL PRIMARY KEY,
    name                    VARCHAR(255) NOT NULL,
    host                    VARCHAR(255) NOT NULL,
    port                    INTEGER NOT NULL DEFAULT 389,
    bind_dn                 TEXT NOT NULL,
    -- Stored as "fernet:<ciphertext>".
    -- Key = base64url(SHA-256(ldap_sync_key secret)) — use crypto_helper.fernet_decrypt().
    -- Never stored in plaintext; GET endpoints always return NULL for this field.
    bind_password_enc       TEXT NOT NULL,
    base_dn                 TEXT NOT NULL,
    user_search_filter      TEXT NOT NULL DEFAULT '(objectClass=person)',
    user_attr_uid           VARCHAR(100) DEFAULT 'sAMAccountName',
    user_attr_mail          VARCHAR(100) DEFAULT 'mail',
    user_attr_fullname      VARCHAR(100) DEFAULT 'displayName',
    use_tls                 BOOLEAN NOT NULL DEFAULT TRUE,
    use_starttls            BOOLEAN NOT NULL DEFAULT FALSE,
    verify_tls_cert         BOOLEAN NOT NULL DEFAULT TRUE,
    ca_cert_pem             TEXT,
    -- TRUE = skip system TOTP for users from this config (IdP handles MFA).
    -- Must be explicit opt-in; FALSE by default.
    mfa_delegated           BOOLEAN NOT NULL DEFAULT FALSE,
    -- TRUE = RFC-1918 / loopback host addresses are permitted.
    -- Superadmin opt-in only; consistent with pf9_control_planes.allow_private_network.
    allow_private_network   BOOLEAN NOT NULL DEFAULT FALSE,
    is_enabled              BOOLEAN NOT NULL DEFAULT TRUE,
    sync_interval_minutes   INTEGER NOT NULL DEFAULT 60,
    last_sync_at            TIMESTAMPTZ,
    last_sync_status        VARCHAR(50)
                            CHECK (last_sync_status IN ('success','partial','failed')),
    last_sync_users_found   INTEGER,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by              VARCHAR(255)
);

CREATE INDEX IF NOT EXISTS idx_ldap_sync_config_enabled
    ON ldap_sync_config(is_enabled) WHERE is_enabled = TRUE;

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. ldap_sync_group_mappings  — external group DN → pf9 RBAC role
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ldap_sync_group_mappings (
    id                SERIAL PRIMARY KEY,
    config_id         INTEGER NOT NULL
                      REFERENCES ldap_sync_config(id) ON DELETE CASCADE,
    external_group_dn TEXT NOT NULL,
    -- 'superadmin' is intentionally excluded — external groups may never grant
    -- superadmin.  That role is reserved for locally-created accounts only.
    pf9_role          VARCHAR(50) NOT NULL
                      CHECK (pf9_role IN ('viewer','operator','admin')),
    UNIQUE(config_id, external_group_dn)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. ldap_sync_log  — audit trail for every sync run
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ldap_sync_log (
    id                  BIGSERIAL PRIMARY KEY,
    config_id           INTEGER REFERENCES ldap_sync_config(id) ON DELETE SET NULL,
    -- Snapshot of the config name at run time; survives if the config is deleted.
    config_name         VARCHAR(255),
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMPTZ,
    status              VARCHAR(50)
                        CHECK (status IN ('success','partial','failed')),
    users_found         INTEGER NOT NULL DEFAULT 0,
    users_created       INTEGER NOT NULL DEFAULT 0,
    users_updated       INTEGER NOT NULL DEFAULT 0,
    users_deactivated   INTEGER NOT NULL DEFAULT 0,
    error_message       TEXT,
    -- Per-user results array for debugging (only populated on partial/failed runs).
    details             JSONB
);

CREATE INDEX IF NOT EXISTS idx_ldap_sync_log_config_id
    ON ldap_sync_log(config_id, started_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. Alter user_roles — track identity source
-- ─────────────────────────────────────────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='user_roles' AND column_name='sync_source'
    ) THEN
        ALTER TABLE user_roles
            ADD COLUMN sync_source TEXT NOT NULL DEFAULT 'local'
                CHECK (sync_source IN ('local','external_ldap'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='user_roles' AND column_name='sync_config_id'
    ) THEN
        ALTER TABLE user_roles
            ADD COLUMN sync_config_id INTEGER
                REFERENCES ldap_sync_config(id) ON DELETE SET NULL;
        -- DELETION GUARD: ON DELETE SET NULL means deleting a config orphans its users.
        -- The DELETE endpoint for ldap_sync_config MUST deactivate + session-revoke
        -- all users with that sync_config_id BEFORE deleting the config row.
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='user_roles' AND column_name='locally_overridden'
    ) THEN
        ALTER TABLE user_roles
            ADD COLUMN locally_overridden BOOLEAN NOT NULL DEFAULT FALSE;
        -- locally_overridden = TRUE prevents the sync worker from overwriting
        -- a role that was manually pinned by a superadmin.
    END IF;
END;
$$;

-- Partial index: sync worker deactivation loop filters on sync_source every run.
CREATE INDEX IF NOT EXISTS idx_user_roles_sync_source
    ON user_roles(sync_source)
    WHERE sync_source <> 'local';

CREATE INDEX IF NOT EXISTS idx_user_roles_sync_config_id
    ON user_roles(sync_config_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. RBAC — superadmin-only permission entries
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO role_permissions (role, resource, action) VALUES
    ('superadmin', 'ldap-sync', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;
