/**
 * Snapshot Audit Trail Component
 * 
 * Displays detailed audit trail of snapshot operations
 * with filtering, search, and export capabilities
 */

import React, { useState, useEffect } from 'react';
import '../styles/SnapshotAuditTrail.css';

interface SnapshotRecord {
  id: number;
  run_id: number;
  tenant_id: string;
  tenant_name: string;
  project_id: string;
  project_name: string;
  vm_id?: string;
  vm_name?: string;
  volume_id: string;
  volume_name: string;
  action: string;
  snapshot_id?: string;
  retention_days?: number;
  error_message?: string;
  created_at: string;
}

interface AuditFilters {
  tenant?: string;
  project?: string;
  action?: string;
  dateRange?: [string, string];
  searchTerm?: string;
}

export const SnapshotAuditTrail: React.FC = () => {
  const [records, setRecords] = useState<SnapshotRecord[]>([]);
  const [filteredRecords, setFilteredRecords] = useState<SnapshotRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<AuditFilters>({});
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [tenants, setTenants] = useState<string[]>([]);
  const [projects, setProjects] = useState<string[]>([]);

  const token = localStorage.getItem('token');

  useEffect(() => {
    loadRecords();
  }, []);

  useEffect(() => {
    filterRecords();
  }, [records, filters, currentPage, pageSize]);

  const loadRecords = async () => {
    setLoading(true);
    setError(null);

    try {
      const res = await fetch('/api/snapshot/records?limit=1000', {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!res.ok) throw new Error('Failed to load audit trail');

      const data = await res.json();
      setRecords(data.records || []);

      // Extract unique tenants and projects for filters
      const uniqueTenants = [...new Set(data.records?.map((r: SnapshotRecord) => r.tenant_name) || [])];
      const uniqueProjects = [...new Set(data.records?.map((r: SnapshotRecord) => r.project_name) || [])];

      setTenants(uniqueTenants as string[]);
      setProjects(uniqueProjects as string[]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load records');
    } finally {
      setLoading(false);
    }
  };

  const filterRecords = () => {
    let filtered = [...records];

    // Apply filters
    if (filters.tenant) {
      filtered = filtered.filter(r => r.tenant_name === filters.tenant);
    }

    if (filters.project) {
      filtered = filtered.filter(r => r.project_name === filters.project);
    }

    if (filters.action) {
      filtered = filtered.filter(r => r.action === filters.action);
    }

    if (filters.searchTerm) {
      const term = filters.searchTerm.toLowerCase();
      filtered = filtered.filter(
        r =>
          r.volume_name.toLowerCase().includes(term) ||
          r.vm_name?.toLowerCase().includes(term) ||
          r.snapshot_id?.toLowerCase().includes(term)
      );
    }

    if (filters.dateRange) {
      const [startDate, endDate] = filters.dateRange;
      filtered = filtered.filter(r => {
        const recordDate = new Date(r.created_at);
        return recordDate >= new Date(startDate) && recordDate <= new Date(endDate);
      });
    }

    // Sort by date descending
    filtered.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

    setFilteredRecords(filtered);
    setCurrentPage(1);
  };

  const handleExport = () => {
    const csv = convertToCSV(filteredRecords);
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `snapshot-audit-trail-${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
  };

  const convertToCSV = (records: SnapshotRecord[]): string => {
    const headers = [
      'ID',
      'Run ID',
      'Tenant',
      'Project',
      'VM',
      'Volume',
      'Action',
      'Snapshot ID',
      'Retention Days',
      'Status',
      'Timestamp',
    ];

    const rows = records.map(r => [
      r.id,
      r.run_id,
      r.tenant_name,
      r.project_name,
      r.vm_name || '—',
      r.volume_name,
      r.action,
      r.snapshot_id || '—',
      r.retention_days || '—',
      r.error_message ? 'Error' : 'Success',
      new Date(r.created_at).toISOString(),
    ]);

    return [
      headers.join(','),
      ...rows.map(row => row.map(cell => `"${cell}"`).join(',')),
    ].join('\n');
  };

  const paginatedRecords = filteredRecords.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize
  );
  const totalPages = Math.ceil(filteredRecords.length / pageSize);

  const getActionBadgeClass = (action: string) => {
    switch (action) {
      case 'created':
        return 'success';
      case 'deleted':
        return 'info';
      case 'failed':
        return 'danger';
      case 'skipped':
        return 'warning';
      default:
        return 'default';
    }
  };

  return (
    <div className="snapshot-audit-trail">
      <h1>Snapshot Audit Trail</h1>

      {error && <div className="alert alert-error">{error}</div>}

      {/* Filters */}
      <div className="filters-section">
        <div className="filter-row">
          <div className="filter-group">
            <label>Search Volume/VM/Snapshot</label>
            <input
              type="text"
              placeholder="Enter volume name, VM, or snapshot ID..."
              value={filters.searchTerm || ''}
              onChange={e => setFilters({ ...filters, searchTerm: e.target.value })}
              className="filter-input"
            />
          </div>

          <div className="filter-group">
            <label>Tenant</label>
            <select
              value={filters.tenant || ''}
              onChange={e => setFilters({ ...filters, tenant: e.target.value || undefined })}
              className="filter-select"
            >
              <option value="">All Tenants</option>
              {tenants.map(tenant => (
                <option key={tenant} value={tenant}>
                  {tenant}
                </option>
              ))}
            </select>
          </div>

          <div className="filter-group">
            <label>Project</label>
            <select
              value={filters.project || ''}
              onChange={e => setFilters({ ...filters, project: e.target.value || undefined })}
              className="filter-select"
            >
              <option value="">All Projects</option>
              {projects.map(project => (
                <option key={project} value={project}>
                  {project}
                </option>
              ))}
            </select>
          </div>

          <div className="filter-group">
            <label>Action</label>
            <select
              value={filters.action || ''}
              onChange={e => setFilters({ ...filters, action: e.target.value || undefined })}
              className="filter-select"
            >
              <option value="">All Actions</option>
              <option value="created">Created</option>
              <option value="deleted">Deleted</option>
              <option value="failed">Failed</option>
              <option value="skipped">Skipped</option>
            </select>
          </div>

          <div className="filter-actions">
            <button className="btn btn-secondary" onClick={loadRecords}>
              Refresh
            </button>
            <button className="btn btn-primary" onClick={handleExport}>
              Export CSV
            </button>
          </div>
        </div>
      </div>

      {/* Records Table */}
      {loading ? (
        <div className="loader">Loading audit trail...</div>
      ) : (
        <>
          <div className="records-info">
            Showing {paginatedRecords.length > 0 ? (currentPage - 1) * pageSize + 1 : 0} to{' '}
            {Math.min(currentPage * pageSize, filteredRecords.length)} of {filteredRecords.length}{' '}
            records
          </div>

          <div className="table-container">
            <table className="audit-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Timestamp</th>
                  <th>Tenant</th>
                  <th>Project</th>
                  <th>VM</th>
                  <th>Volume</th>
                  <th>Action</th>
                  <th>Snapshot ID</th>
                  <th>Status</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {paginatedRecords.length === 0 ? (
                  <tr>
                    <td colSpan={10} className="empty-cell">
                      No records found
                    </td>
                  </tr>
                ) : (
                  paginatedRecords.map(record => (
                    <tr key={record.id}>
                      <td>#{record.id}</td>
                      <td>
                        <small>
                          {new Date(record.created_at).toLocaleString()}
                        </small>
                      </td>
                      <td>{record.tenant_name}</td>
                      <td>{record.project_name}</td>
                      <td>{record.vm_name || '—'}</td>
                      <td>
                        <strong>{record.volume_name}</strong>
                        <br />
                        <small>{record.volume_id}</small>
                      </td>
                      <td>
                        <span className={`badge action-${getActionBadgeClass(record.action)}`}>
                          {record.action}
                        </span>
                      </td>
                      <td>
                        <code>{record.snapshot_id || '—'}</code>
                      </td>
                      <td>
                        {record.error_message ? (
                          <span className="badge status-error" title={record.error_message}>
                            Error
                          </span>
                        ) : (
                          <span className="badge status-success">Success</span>
                        )}
                      </td>
                      <td>
                        {record.retention_days && (
                          <span>Retention: {record.retention_days}d</span>
                        )}
                        {record.error_message && (
                          <div className="error-details">{record.error_message}</div>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="pagination">
              <button
                disabled={currentPage === 1}
                onClick={() => setCurrentPage(1)}
                className="btn btn-sm"
              >
                First
              </button>
              <button
                disabled={currentPage === 1}
                onClick={() => setCurrentPage(currentPage - 1)}
                className="btn btn-sm"
              >
                Previous
              </button>

              <span className="page-info">
                Page {currentPage} of {totalPages}
              </span>

              <button
                disabled={currentPage === totalPages}
                onClick={() => setCurrentPage(currentPage + 1)}
                className="btn btn-sm"
              >
                Next
              </button>
              <button
                disabled={currentPage === totalPages}
                onClick={() => setCurrentPage(totalPages)}
                className="btn btn-sm"
              >
                Last
              </button>

              <select
                value={pageSize}
                onChange={e => setPageSize(Number(e.target.value))}
                className="page-size-select"
              >
                <option value={10}>10 per page</option>
                <option value={25}>25 per page</option>
                <option value={50}>50 per page</option>
                <option value={100}>100 per page</option>
              </select>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default SnapshotAuditTrail;
