-- Performance indexes — Phase O3 (March 15, 2026)
-- All statements use CREATE INDEX IF NOT EXISTS and are safe to re-run.
-- Run order: independent of all other migrations (no schema changes).

-- inventory_runs: dashboard and report queries filter/sort by started_at
CREATE INDEX IF NOT EXISTS idx_inventory_runs_started_at
    ON inventory_runs (started_at DESC);

-- activity_log: audit queries filter by user and sort recency
CREATE INDEX IF NOT EXISTS idx_activity_log_user_created
    ON activity_log (actor, timestamp DESC);

-- activity_log: timestamp-only queries (admin timeline, SLA reports)
CREATE INDEX IF NOT EXISTS idx_activity_log_created_at
    ON activity_log (timestamp DESC);

-- snapshots: snapshot tab queries filter by project and sort by creation time
CREATE INDEX IF NOT EXISTS idx_snapshots_project_created
    ON snapshots (project_id, created_at DESC);

-- migration_vms: migration planner queries always scope to a single project
CREATE INDEX IF NOT EXISTS idx_migration_vms_project_id
    ON migration_vms (project_id);

-- support_tickets: ticket list queries filter by status and/or department
CREATE INDEX IF NOT EXISTS idx_tickets_status_dept
    ON support_tickets (status, to_dept_id);

-- support_tickets: SLA breach queries filter by sla_resolve_at
CREATE INDEX IF NOT EXISTS idx_tickets_due_date
    ON support_tickets (sla_resolve_at) WHERE sla_resolve_at IS NOT NULL;

-- runbook_executions: history queries filter by runbook_name and sort by started_at
CREATE INDEX IF NOT EXISTS idx_runbook_exec_runbook_started
    ON runbook_executions (runbook_name, started_at DESC);
