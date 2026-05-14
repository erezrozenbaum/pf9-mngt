-- migrate_v1_98_0_audit_append_only.sql
-- Make audit log tables append-only using triggers.
-- RLS is not enforced for superusers, so we use BEFORE DELETE/UPDATE triggers
-- that always raise an exception. This blocks accidental or malicious deletion
-- of audit records regardless of the caller's role.
-- The scheduler's history archival explicitly excludes these tables.
--
-- Applied idempotently via schema_migrations tracking.

-- Shared trigger function
CREATE OR REPLACE FUNCTION fn_audit_log_append_only()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Audit log is append-only: % on % is not permitted', TG_OP, TG_TABLE_NAME;
END;
$$;

-- auth_audit_log: block DELETE
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_auth_audit_no_delete'
          AND tgrelid = 'auth_audit_log'::regclass
    ) THEN
        CREATE TRIGGER trg_auth_audit_no_delete
            BEFORE DELETE ON auth_audit_log
            FOR EACH ROW EXECUTE FUNCTION fn_audit_log_append_only();
    END IF;
END;
$$;

-- auth_audit_log: block UPDATE
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_auth_audit_no_update'
          AND tgrelid = 'auth_audit_log'::regclass
    ) THEN
        CREATE TRIGGER trg_auth_audit_no_update
            BEFORE UPDATE ON auth_audit_log
            FOR EACH ROW EXECUTE FUNCTION fn_audit_log_append_only();
    END IF;
END;
$$;

-- tenant_action_log: block DELETE
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_tenant_action_no_delete'
          AND tgrelid = 'tenant_action_log'::regclass
    ) THEN
        CREATE TRIGGER trg_tenant_action_no_delete
            BEFORE DELETE ON tenant_action_log
            FOR EACH ROW EXECUTE FUNCTION fn_audit_log_append_only();
    END IF;
END;
$$;

-- tenant_action_log: block UPDATE
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_tenant_action_no_update'
          AND tgrelid = 'tenant_action_log'::regclass
    ) THEN
        CREATE TRIGGER trg_tenant_action_no_update
            BEFORE UPDATE ON tenant_action_log
            FOR EACH ROW EXECUTE FUNCTION fn_audit_log_append_only();
    END IF;
END;
$$;

INSERT INTO schema_migrations (filename, applied_at)
VALUES ('migrate_v1_98_0_audit_append_only.sql', NOW())
ON CONFLICT (filename) DO NOTHING;
