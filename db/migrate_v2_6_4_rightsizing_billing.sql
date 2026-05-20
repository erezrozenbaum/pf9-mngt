-- =====================================================================
-- Migration: Right-Sizing Billing Impact + Tenant Resize Request CTA
-- Version:  2.6.4
-- =====================================================================
--
-- Changes:
--   1. Grant SELECT, UPDATE on rightsizing_recommendations to tenant_portal_role
--      (required by POST /tenant/rightsizing/{id}/request-change endpoint
--       which sets status='actioned' when a tenant submits a resize request)
--   2. Grant SELECT on metering_flavor_pricing to tenant_portal_role
--      (required by tenant portal cost computation in _load_flavor_prices())
--   3. Add GET /api/rightsizing/projects endpoint (no schema change —
--      reads distinct project_name from existing rows)
--   4. Billing cost data is computed at runtime from metering_flavor_pricing /
--      metering_pricing; no schema changes required.
-- =====================================================================

DO $$
BEGIN
    -- Upgrade tenant_portal_role from SELECT-only to SELECT+UPDATE so that
    -- the request-change endpoint can mark recommendations as 'actioned'.
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenant_portal_role') THEN
        GRANT SELECT, UPDATE ON rightsizing_recommendations TO tenant_portal_role;
        -- Allow tenant portal to read flavor pricing for billing cost display.
        GRANT SELECT ON metering_flavor_pricing TO tenant_portal_role;
    END IF;
END $$;
