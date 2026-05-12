-- ============================================================
-- Migration v1.95.21: Provisioning request_payload column
-- Adds JSONB column to persist the full ProvisionRequest on
-- job creation, enabling one-click retry of failed jobs via
-- POST /api/provisioning/retry/{job_id}.
-- ============================================================

ALTER TABLE provisioning_jobs
    ADD COLUMN IF NOT EXISTS request_payload JSONB;

COMMENT ON COLUMN provisioning_jobs.request_payload IS
    'Full ProvisionRequest serialised as JSON on job creation — used by the retry endpoint to re-run a failed job without re-submitting the form';
