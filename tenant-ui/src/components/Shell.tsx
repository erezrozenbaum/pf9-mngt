import { useState, useEffect } from "react";
import type { Branding, MeResponse, InventoryStatus } from "../lib/api";
import { apiInventoryStatus } from "../lib/api";
import type { Screen } from "../App";
import { Dashboard } from "../screens/Dashboard";
import { Infrastructure } from "../screens/Infrastructure";
import { SnapshotCoverage } from "../screens/SnapshotCoverage";
import { Monitoring } from "../screens/Monitoring";
import { RestoreCenter } from "../screens/RestoreCenter";
import { Runbooks } from "../screens/Runbooks";
import { ActivityLog } from "../screens/ActivityLog";
import { Reports } from "../screens/Reports";
import { Provision } from "../screens/Provision";

interface Props {
  branding: Branding;
  me: MeResponse;
  screen: Screen;
  onNavigate: (s: Screen) => void;
  onLogout: () => void;
}

const NAV_ITEMS: Array<{ id: Screen; label: string; icon: string }> = [
  { id: "dashboard",      label: "Dashboard",           icon: "▦" },
  { id: "infrastructure", label: "My Infrastructure",   icon: "🖥" },
  { id: "snapshots",      label: "Snapshot Coverage",   icon: "🗂" },
  { id: "monitoring",     label: "Monitoring",           icon: "📊" },
  { id: "restore",        label: "Restore Center",       icon: "↺" },
  { id: "runbooks",       label: "Runbooks",             icon: "📖" },
  { id: "reports",        label: "Reports",              icon: "📄" },
  { id: "provision",      label: "New VM",               icon: "🚀" },
  { id: "activity",       label: "Activity Log",         icon: "📋" },
];

const SCREEN_TITLES: Record<Screen, string> = {
  dashboard:      "Dashboard",
  infrastructure: "My Infrastructure",
  snapshots:      "Snapshot Coverage",
  monitoring:     "Monitoring & Availability",
  restore:        "Restore Center",
  runbooks:       "Runbooks",
  reports:        "Reports",
  provision:      "New VM",
  activity:       "Activity Log",
};

export function Shell({ branding, me, screen, onNavigate, onLogout }: Props) {
  const [regionFilter, setRegionFilter] = useState<string>("");
  const [refreshTick, setRefreshTick] = useState(0);
  const [inventoryStatus, setInventoryStatus] = useState<InventoryStatus | null>(null);
  const [syncLoading, setSyncLoading] = useState(false);

  const fetchInventoryStatus = () => {
    setSyncLoading(true);
    apiInventoryStatus()
      .then(setInventoryStatus)
      .catch(() => { /* non-critical */ })
      .finally(() => setSyncLoading(false));
  };

  useEffect(() => { fetchInventoryStatus(); }, []);

  const renderScreen = () => {
    switch (screen) {
      case "dashboard":      return <Dashboard      key={refreshTick} regionFilter={regionFilter} />;
      case "infrastructure": return <Infrastructure key={refreshTick} regionFilter={regionFilter} />;
      case "snapshots":      return <SnapshotCoverage key={refreshTick} regionFilter={regionFilter} />;
      case "monitoring":     return <Monitoring     key={refreshTick} regionFilter={regionFilter} />;
      case "restore":        return <RestoreCenter  key={refreshTick} />;
      case "runbooks":       return <Runbooks       key={refreshTick} />;
      case "reports":        return <Reports        key={refreshTick} />;
      case "provision":      return <Provision      key={refreshTick} />;
      case "activity":       return <ActivityLog    key={refreshTick} />;
    }
  };

  const projectCount = me.projects.length;

  return (
    <div className="shell">
      {/* ── Sidebar ── */}
      <nav className="sidebar" aria-label="Main navigation">
        <div className="sidebar-brand">
          {branding.logo_url ? (
            <img src={branding.logo_url} alt={branding.company_name} className="sidebar-logo" />
          ) : (
            <div className="sidebar-logo-text">{branding.company_name}</div>
          )}
        </div>

        {/* Region selector — only shown when the tenant has multiple regions */}
        {me.regions.length > 1 && (
          <div style={{ padding: "0 .75rem .625rem" }}>
            <label style={{
              color: "rgba(255,255,255,.5)",
              fontSize: ".7rem",
              fontWeight: 600,
              display: "block",
              marginBottom: ".25rem",
              textTransform: "uppercase",
              letterSpacing: ".05em",
            }}>
              Region
            </label>
            <select
              className="select"
              style={{
                width: "100%",
                background: "rgba(255,255,255,.08)",
                color: "#fff",
                border: "1px solid rgba(255,255,255,.15)",
                fontSize: ".8rem",
              }}
              value={regionFilter}
              onChange={(e) => setRegionFilter(e.target.value)}
            >
              <option value="">All regions</option>
              {me.regions.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </div>
        )}

        <div style={{ flex: 1 }}>
          {NAV_ITEMS.map(({ id, label, icon }) => (
            <button
              key={id}
              className={`nav-item${screen === id ? " active" : ""}`}
              onClick={() => onNavigate(id)}
              aria-current={screen === id ? "page" : undefined}
            >
              <span aria-hidden="true" style={{ fontSize: ".9rem", width: "1.1rem", flexShrink: 0 }}>{icon}</span>
              {label}
            </button>
          ))}
        </div>

        <div className="sidebar-footer">
          {me.username && (
            <div style={{
              color: "rgba(255,255,255,.6)",
              fontSize: ".75rem",
              marginBottom: ".5rem",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}>
              {me.username}
            </div>
          )}
          <button
            className="btn btn-secondary"
            style={{ width: "100%", justifyContent: "center", fontSize: ".8125rem" }}
            onClick={onLogout}
          >
            Sign out
          </button>
        </div>
      </nav>

      {/* ── Main area ── */}
      <div className="main-area">
        <header className="page-header">
          <h1 className="page-title">{SCREEN_TITLES[screen]}</h1>
          <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
            {inventoryStatus?.last_sync_at && (
              <span style={{ fontSize: ".75rem", color: "var(--color-text-secondary)" }}>
                Inventory synced{" "}
                {inventoryStatus.minutes_ago === 0
                  ? "just now"
                  : `${inventoryStatus.minutes_ago} min ago`}
              </span>
            )}
            {!inventoryStatus?.last_sync_at && !syncLoading && (
              <span style={{ fontSize: ".75rem", color: "var(--color-text-secondary)" }}>Inventory sync unknown</span>
            )}
            <button
              className="btn btn-secondary"
              style={{ padding: ".25rem .65rem", fontSize: ".75rem" }}
              disabled={syncLoading}
              onClick={() => {
                setRefreshTick((t) => t + 1);
                fetchInventoryStatus();
              }}
              title="Reload current screen data"
            >
              {syncLoading ? <span className="loading-spinner" style={{ width: "10px", height: "10px" }} /> : "⟳ Refresh"}
            </button>
            {projectCount > 0 && (
              <span style={{ fontSize: ".8125rem", color: "var(--color-text-secondary)" }}>
                {projectCount} project{projectCount > 1 ? "s" : ""}
                {regionFilter && ` · ${regionFilter}`}
              </span>
            )}
          </div>
        </header>
        <div className="page-body">
          {renderScreen()}
        </div>
      </div>
    </div>
  );
}
