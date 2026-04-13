-- B9.1: Performance indexes for high-frequency query paths
-- All statements are idempotent (IF NOT EXISTS).
-- Run inside a startup advisory-lock block.

-- servers: project-scoped VM listing and status filtering (most common dashboard query)
CREATE INDEX IF NOT EXISTS idx_servers_project_status
    ON servers(project_id, status);

-- servers: hypervisor drill-down (no existing index on hypervisor_hostname)
CREATE INDEX IF NOT EXISTS idx_servers_hypervisor
    ON servers(hypervisor_hostname);

-- servers: staleness detection (collector marks stale VMs by last_seen_at)
CREATE INDEX IF NOT EXISTS idx_servers_last_seen
    ON servers(last_seen_at DESC);

-- volumes: project-scoped volume listing and status filtering
CREATE INDEX IF NOT EXISTS idx_volumes_project_status
    ON volumes(project_id, status);

-- snapshots: project-scoped snapshot listing (no existing index on project_id or created_at)
CREATE INDEX IF NOT EXISTS idx_snapshots_project_created
    ON snapshots(project_id, created_at DESC);

-- snapshots: volume → snapshot lookup (volume_id not indexed)
CREATE INDEX IF NOT EXISTS idx_snapshots_volume_id
    ON snapshots(volume_id);

-- restore_jobs: active jobs dashboard (status + chronological order, compound avoids index-merge)
CREATE INDEX IF NOT EXISTS idx_restore_jobs_status_created
    ON restore_jobs(status, created_at DESC);

-- drift_events: domain-scoped drift summary (project_id already indexed; domain_id is not)
CREATE INDEX IF NOT EXISTS idx_drift_events_domain
    ON drift_events(domain_id);

-- drift_events: unacknowledged-by-domain compound for summary endpoint
CREATE INDEX IF NOT EXISTS idx_drift_events_domain_ack
    ON drift_events(domain_id, acknowledged);

-- snapshot_records: vm + time compound (vm_id alone exists; compound avoids second sort)
CREATE INDEX IF NOT EXISTS idx_snapshot_records_vm_created
    ON snapshot_records(vm_id, created_at DESC);
