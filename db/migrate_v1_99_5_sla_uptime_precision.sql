-- Migration v1.99.5: widen sla_compliance_monthly.uptime_actual_pct
--
-- DECIMAL(5,3) allows values up to 99.999. A tenant with 100% uptime
-- (active_servers == total_servers) produces 100.000 which overflows.
-- DECIMAL(6,3) allows values up to 999.999, properly accommodating 100.000.

ALTER TABLE sla_compliance_monthly
    ALTER COLUMN uptime_actual_pct TYPE DECIMAL(6,3);
