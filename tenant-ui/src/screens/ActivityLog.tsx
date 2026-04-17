import React, { useEffect, useState } from "react";
import { apiActivity, type ActivityRow } from "../lib/api";

// ── Action label map ─────────────────────────────────────────────────────────

const ACTION_LABELS: Record<string, string> = {
  tenant_login:              "Login",
  tenant_login_failed:       "Login Failed",
  tenant_logout:             "Logout",
  tenant_view_dashboard:     "Viewed Dashboard",
  tenant_view_vms:           "Viewed VMs",
  tenant_view_vm_detail:     "Viewed VM Detail",
  tenant_view_volumes:       "Viewed Volumes",
  tenant_view_snapshots:     "Viewed Snapshots",
  tenant_view_snapshot_detail: "Viewed Snapshot",
  tenant_view_compliance:    "Viewed Compliance",
  tenant_view_metrics:       "Viewed Metrics",
  tenant_view_availability:  "Viewed Availability",
  tenant_view_restore_jobs:  "Viewed Restore Jobs",
  tenant_view_runbooks:      "Viewed Runbooks",
  tenant_view_runbook_detail:"Viewed Runbook",
  tenant_restore_plan:       "Restore Planned",
  tenant_restore_execute:    "Restore Executed",
  tenant_restore_cancel:     "Restore Cancelled",
  tenant_restore_completed:  "Restore Completed",
  tenant_restore_failed:     "Restore Failed",
  tenant_ip_mismatch:        "IP Address Changed",
};

function labelFor(action: string): string {
  return ACTION_LABELS[action] ?? action.replace(/^tenant_/, "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// ── Main component ───────────────────────────────────────────────────────────

export function ActivityLog() {
  const [rows, setRows] = useState<ActivityRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [actionFilter, setActionFilter] = useState("");

  const load = (params?: { from_date?: string; to_date?: string; action?: string }) => {
    setLoading(true);
    setError(null);
    apiActivity(params)
      .then(setRows)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleFilter = (e: React.FormEvent) => {
    e.preventDefault();
    load({
      from_date: fromDate  || undefined,
      to_date:   toDate    || undefined,
      action:    actionFilter.trim() || undefined,
    });
  };

  const handleReset = () => {
    setFromDate("");
    setToDate("");
    setActionFilter("");
    load();
  };

  return (
    <div>
      {/* ── Filter bar ── */}
      <form
        onSubmit={handleFilter}
        style={{ display: "flex", gap: ".75rem", flexWrap: "wrap", marginBottom: "1rem", alignItems: "flex-end" }}
      >
        <div className="field" style={{ marginBottom: 0 }}>
          <label>From</label>
          <input
            className="input"
            type="date"
            value={fromDate}
            onChange={(e) => setFromDate(e.target.value)}
            style={{ width: "160px" }}
          />
        </div>
        <div className="field" style={{ marginBottom: 0 }}>
          <label>To</label>
          <input
            className="input"
            type="date"
            value={toDate}
            onChange={(e) => setToDate(e.target.value)}
            style={{ width: "160px" }}
          />
        </div>
        <div className="field" style={{ marginBottom: 0 }}>
          <label>Action</label>
          <input
            className="input"
            type="text"
            placeholder="e.g. tenant_login"
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
            style={{ width: "200px" }}
          />
        </div>
        <div style={{ display: "flex", gap: ".5rem", alignSelf: "flex-end", paddingBottom: "1px" }}>
          <button type="submit" className="btn btn-primary">Filter</button>
          <button type="button" className="btn btn-secondary" onClick={handleReset}>Reset</button>
        </div>
      </form>

      {loading && <div className="empty-state"><span className="loading-spinner" /></div>}
      {error   && <div className="error-banner">{error}</div>}

      {!loading && !error && rows.length === 0 && (
        <div className="empty-state">No activity found for the selected period.</div>
      )}

      {!loading && !error && rows.length > 0 && (
        <div className="card table-wrap" style={{ padding: 0 }}>
          <table>
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>User</th>
                <th>Action</th>
                <th>Resource</th>
                <th>IP Address</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td style={{ fontFamily: "monospace", fontSize: ".8rem", whiteSpace: "nowrap" }}>
                    {new Date(row.timestamp).toLocaleString()}
                  </td>
                  <td>
                    {row.username ? (
                      <div>
                        <div style={{ fontSize: ".8125rem", fontWeight: 500 }}>{row.username}</div>
                        {row.keystone_user_id && (
                          <div style={{ fontSize: ".7rem", color: "var(--color-text-secondary)", fontFamily: "monospace" }}>
                            {row.keystone_user_id.slice(0, 12)}…
                          </div>
                        )}
                      </div>
                    ) : (
                      <span style={{ color: "var(--color-text-secondary)", fontSize: ".8rem" }}>system</span>
                    )}
                  </td>
                  <td>{labelFor(row.action)}</td>
                  <td>
                    {row.resource_type && (
                      <span style={{ fontSize: ".8125rem" }}>
                        {row.resource_type}
                        {row.resource_id && (
                          <span style={{ color: "var(--color-text-secondary)", marginLeft: ".3rem" }}>
                            · {row.resource_id.slice(0, 8)}…
                          </span>
                        )}
                      </span>
                    )}
                  </td>
                  <td style={{ fontFamily: "monospace", fontSize: ".8rem" }}>
                    {row.ip_address ?? "—"}
                  </td>
                  <td>
                    {row.success
                      ? <span className="badge badge-green">OK</span>
                      : <span className="badge badge-red">Failed</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
