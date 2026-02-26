-- ============================================================
-- Add vCPU and Memory usage percentage columns to migration_vms
-- Extracted from RVTools vCPU and vMemory sheets for sizing assessments
-- ============================================================

-- Add CPU and memory usage percentage columns
ALTER TABLE migration_vms 
ADD COLUMN IF NOT EXISTS cpu_usage_percent NUMERIC(6,2),
ADD COLUMN IF NOT EXISTS memory_usage_percent NUMERIC(6,2),
ADD COLUMN IF NOT EXISTS cpu_demand_mhz BIGINT,
ADD COLUMN IF NOT EXISTS memory_usage_mb BIGINT;

-- Create indexes for usage queries
CREATE INDEX IF NOT EXISTS idx_mig_vms_cpu_usage 
    ON migration_vms(project_id, cpu_usage_percent) WHERE cpu_usage_percent IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_mig_vms_memory_usage 
    ON migration_vms(project_id, memory_usage_percent) WHERE memory_usage_percent IS NOT NULL;

-- Add comments for documentation
COMMENT ON COLUMN migration_vms.cpu_usage_percent IS 'CPU usage percentage from RVTools vCPU sheet';
COMMENT ON COLUMN migration_vms.memory_usage_percent IS 'Memory usage percentage from RVTools vMemory sheet';
COMMENT ON COLUMN migration_vms.cpu_demand_mhz IS 'CPU demand in MHz from RVTools vCPU sheet';
COMMENT ON COLUMN migration_vms.memory_usage_mb IS 'Memory usage in MB from RVTools vMemory sheet';