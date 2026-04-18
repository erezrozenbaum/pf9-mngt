import { useEffect, useState } from "react";
import {
  apiCompliance,
  apiSnapshotHistory,
  apiSnapshots,
  type ComplianceRow,
  type SnapshotRecord,
  type Snapshot,
} from "../lib/api";

// ── Calendar helpers ─────────────────────────────────────────────────────────

type DayStatus = "ok" | "fail" | "none";

function buildCalendarData(records: SnapshotRecord[]): Map<string, Map<string, DayStatus>> {
  const result = new Map<string, Map<string, DayStatus>>();
  for (const r of records) {
    if (!result.has(r.vm_id)) result.set(r.vm_id, new Map());
    const dateKey = r.run_date.slice(0, 10);
    const existing = result.get(r.vm_id)!.get(dateKey);
    const isOk = r.status.toLowerCase() === "success";
    // A day is "ok" if at least one snapshot succeeded; "fail" only if all failed
    if (!existing || (existing === "fail" && isOk)) {
      result.get(r.vm_id)!.set(dateKey, isOk ? "ok" : "fail");
    }
  }
  return result;
}

function getLast30Days(): string[] {
  const days: string[] = [];
  const now = new Date();
  for (let i = 29; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(now.getDate() - i);
    days.push(d.toISOString().slice(0, 10));
  }
  return days;
}

const STATUS_CELL_CLASS: Record<DayStatus | "none", string> = {
  ok:   "calendar-cell cal-green",
  fail: "calendar-cell cal-red",
  none: "calendar-cell cal-grey",
};

// ── CalendarGrid ─────────────────────────────────────────────────────────────

interface CalRow { label: string; vmId: string; data: Map<string, DayStatus>; }

function CalendarGrid({ rows, days }: { rows: CalRow[]; days: string[] }) {
  const today = new Date().toISOString().slice(0, 10);

  return (
    <div style={{ overflowX: "auto" }}>
      {/* Date header — one label per 5-day group (each group = 5 × 17px = 85px) */}
      <div style={{ display: "flex", paddingLeft: "124px", marginBottom: "4px" }}>
        {days
          .filter((_, i) => i % 5 === 0)
          .map((d) => (
            <div key={d} style={{ width: "85px", fontSize: ".65rem", color: "var(--color-text-secondary)", flexShrink: 0 }}>
              {new Date(d + "T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" })}
            </div>
          ))}
      </div>

      {rows.map(({ label, vmId, data }) => (
        <div key={vmId} style={{ display: "flex", alignItems: "center", marginBottom: "3px" }}>
          <div style={{
            width: "120px",
            flexShrink: 0,
            paddingRight: ".5rem",
            fontSize: ".75rem",
            fontWeight: 500,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }} title={label}>
            {label}
          </div>
          <div style={{ display: "flex", gap: "3px" }}>
            {days.map((d) => {
              const val: DayStatus = data.get(d) ?? "none";
              const isToday = d === today;
              return (
                <div
                  key={d}
                  className={STATUS_CELL_CLASS[val]}
                  title={`${d}${isToday ? " (today)" : ""}: ${val === "ok" ? "Snapshot OK" : val === "fail" ? "Snapshot failed" : "No snapshot"}`}
                  style={isToday ? { outline: "2px solid var(--brand-primary, #1A73E8)", outlineOffset: "1px", borderRadius: "2px" } : undefined}
                />
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

interface Props {
  regionFilter: string;
}

export function SnapshotCoverage({ regionFilter }: Props) {
  const [compliance, setCompliance] = useState<ComplianceRow[]>([]);
  const [history, setHistory] = useState<SnapshotRecord[]>([]);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"calendar" | "list">("calendar");

  useEffect(() => {
    let active = true;
    setLoading(true);
    Promise.all([apiCompliance(), apiSnapshotHistory(), apiSnapshots()])
      .then(([c, h, s]) => {
        if (!active) return;
        setCompliance(c);
        setHistory(h);
        setSnapshots(s);
      })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : "Failed to load"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  if (loading) return <div className="empty-state"><span className="loading-spinner" /></div>;
  if (error)   return <div className="error-banner">{error}</div>;

  const filteredCompliance = regionFilter
    ? compliance.filter((c) => c.region_display_name === regionFilter)
    : compliance;

  const filteredSnapshots = regionFilter
    ? snapshots.filter((s) => s.region_display_name === regionFilter)
    : snapshots;

  const calData = buildCalendarData(history);
  const days = getLast30Days();
  const calRows: CalRow[] = filteredCompliance.map((c) => ({
    label: c.vm_name,
    vmId:  c.vm_id,
    data:  calData.get(c.vm_id) ?? new Map(),
  }));

  return (
    <div>
      {/* ── Coverage summary table ── */}
      <div style={{ marginBottom: "1.5rem" }}>
        <div className="section-title">VM Coverage Summary</div>
        <div className="card table-wrap" style={{ padding: 0 }}>
          {filteredCompliance.length === 0 ? (
            <div className="empty-state">No VMs found.</div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>VM</th>
                  <th>Region</th>
                  <th>30d Coverage</th>
                  <th>Streak</th>
                  <th>Last Snapshot</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {filteredCompliance.map((c) => {
                  const pct = c.coverage_pct;
                  const color =
                    pct >= 90 ? "var(--color-success)" :
                    pct >= 70 ? "var(--color-warning)" :
                    "var(--color-error)";
                  return (
                    <tr key={c.vm_id}>
                      <td style={{ fontWeight: 500 }}>{c.vm_name}</td>
                      <td>{c.region_display_name}</td>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: ".5rem" }}>
                          <div className="progress-track" style={{ width: "70px" }}>
                            <div className="progress-fill" style={{ width: `${pct}%`, background: color }} />
                          </div>
                          <span style={{ color, fontWeight: 600, fontSize: ".8125rem" }}>{pct.toFixed(0)}%</span>
                        </div>
                      </td>
                      <td>
                        {c.current_streak > 0
                          ? <span style={{ color: "var(--color-success)", fontWeight: 600 }}>{c.current_streak}d</span>
                          : <span style={{ color: "var(--color-text-secondary)" }}>0</span>}
                      </td>
                      <td>{c.last_snapshot_ts ? new Date(c.last_snapshot_ts).toLocaleDateString() : "—"}</td>
                      <td>
                        {c.status === "ok" || c.status === "covered"
                          ? <span className="badge badge-green">Covered</span>
                          : c.status === "partial"
                          ? <span className="badge badge-amber">Partial</span>
                          : <span className="badge badge-red">Uncovered</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* ── Calendar / Snapshot list tabs ── */}
      <div className="tabs">
        <button className={`tab-btn${tab === "calendar" ? " active" : ""}`} onClick={() => setTab("calendar")}>
          Snapshot Calendar (30d)
        </button>
        <button className={`tab-btn${tab === "list" ? " active" : ""}`} onClick={() => setTab("list")}>
          Snapshot List ({filteredSnapshots.length})
        </button>
      </div>

      {tab === "calendar" && (
        <div className="card">
          {/* Legend */}
          <div style={{ display: "flex", gap: "1rem", marginBottom: ".75rem", flexWrap: "wrap" }}>
            {([
              ["cal-green", "Snapshot OK"],
              ["cal-red",   "Failed"],
              ["cal-grey",  "No snapshot"],
            ] as const).map(([cls, label]) => (
              <div key={cls} style={{ display: "flex", alignItems: "center", gap: ".35rem" }}>
                <div className={`calendar-cell ${cls}`} />
                <span style={{ fontSize: ".75rem", color: "var(--color-text-secondary)" }}>{label}</span>
              </div>
            ))}
          </div>
          {calRows.length === 0 ? (
            <div className="empty-state">No VMs to display.</div>
          ) : (
            <CalendarGrid rows={calRows} days={days} />
          )}
        </div>
      )}

      {tab === "list" && (
        <div className="card table-wrap" style={{ padding: 0 }}>
          {filteredSnapshots.length === 0 ? (
            <div className="empty-state">No snapshots found.</div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>VM</th>
                  <th>Snapshot</th>
                  <th>Date</th>
                  <th>Size</th>
                  <th>Region</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {filteredSnapshots.map((s) => (
                  <tr key={s.snapshot_id}>
                    <td>{s.vm_name}</td>
                    <td style={{ fontFamily: "monospace", fontSize: ".8rem" }}>{s.snapshot_name}</td>
                    <td>{new Date(s.created_at).toLocaleString()}</td>
                    <td>{s.size_gb !== null ? `${s.size_gb.toFixed(1)} GB` : "—"}</td>
                    <td>{s.region_display_name}</td>
                    <td>
                      {s.status.toLowerCase() === "available"
                        ? <span className="badge badge-green">Available</span>
                        : s.status.toLowerCase() === "failed"
                        ? <span className="badge badge-red">Failed</span>
                        : <span className="badge badge-amber">{s.status}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
