-- Migration: Add schedule-aware planning columns to migration_projects
-- These columns drive the schedule-aware agent sizing recommendation engine.

-- Project duration in calendar days (e.g. 30, 60, 90)
ALTER TABLE migration_projects
    ADD COLUMN IF NOT EXISTS migration_duration_days INTEGER DEFAULT 30;

-- Hours per day migration traffic is allowed (e.g. 8 for business hours, 24 for 24x7)
ALTER TABLE migration_projects
    ADD COLUMN IF NOT EXISTS working_hours_per_day NUMERIC(4,1) DEFAULT 8.0;

-- Working days per week (5 = weekdays, 7 = continuous)
ALTER TABLE migration_projects
    ADD COLUMN IF NOT EXISTS working_days_per_week INTEGER DEFAULT 5;

-- Optional: user-specified target VMs per day (NULL = auto-calculate from duration)
ALTER TABLE migration_projects
    ADD COLUMN IF NOT EXISTS target_vms_per_day INTEGER;
