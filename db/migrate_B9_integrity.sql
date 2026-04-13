-- B9.4: Referential integrity — add FK constraints that are currently missing.
-- Uses NOT VALID so existing rows are NOT scanned (instant, no table lock on large tables).
-- A background VALIDATE CONSTRAINT pass is optional and can be run off-hours.

-- restore_jobs.project_id → projects.id
-- Prevents restore jobs being created for non-existent projects.
-- ON DELETE RESTRICT keeps history intact when a project is deleted (admin must clean up manually).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_type='FOREIGN KEY'
          AND table_name='restore_jobs'
          AND constraint_name='fk_restore_jobs_project'
    ) THEN
        ALTER TABLE restore_jobs
            ADD CONSTRAINT fk_restore_jobs_project
            FOREIGN KEY (project_id) REFERENCES projects(id)
            ON DELETE RESTRICT
            NOT VALID;
        RAISE NOTICE 'Added fk_restore_jobs_project (NOT VALID)';
    ELSE
        RAISE NOTICE 'fk_restore_jobs_project already exists — skipped';
    END IF;
END $$;

-- snapshot_records.vm_id → servers.id
-- Prevents orphaned snapshot records when a VM is deleted.
-- ON DELETE SET NULL preserves history with a null vm_id.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_type='FOREIGN KEY'
          AND table_name='snapshot_records'
          AND constraint_name='fk_snapshot_records_server'
    ) THEN
        ALTER TABLE snapshot_records
            ADD CONSTRAINT fk_snapshot_records_server
            FOREIGN KEY (vm_id) REFERENCES servers(id)
            ON DELETE SET NULL
            NOT VALID;
        RAISE NOTICE 'Added fk_snapshot_records_server (NOT VALID)';
    ELSE
        RAISE NOTICE 'fk_snapshot_records_server already exists — skipped';
    END IF;
END $$;
