-- Migration: v1.95.4 billing sales_person_id FK fix
-- The sales_person_id FK referenced users(id) (Keystone UUID) but the admin UI
-- sends the LDAP uid (= users.name) as the sales person identifier. This caused
-- every billing config save to fail with a FK violation.
-- Fix: drop the FK constraint. The JOIN in the API already uses u.name.

ALTER TABLE tenant_billing_config
    DROP CONSTRAINT IF EXISTS tenant_billing_config_sales_person_id_fkey;
