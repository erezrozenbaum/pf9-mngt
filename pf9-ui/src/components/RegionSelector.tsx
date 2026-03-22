/**
 * RegionSelector.tsx — Compact region filter dropdown for the top nav bar.
 *
 * Only renders when:
 *  - The current user is superadmin (ClusterContext only loads data for superadmin)
 *  - There are multiple enabled regions registered (no point filtering on a single region)
 *
 * Selecting "All Regions" sets selectedRegionId to null — the backend
 * aggregates across all regions in that case, preserving existing behavior.
 */

import React from "react";
import { useClusterContext } from "./ClusterContext";

const HEALTH_DOT: Record<string, string> = {
  healthy: "🟢",
  degraded: "🟡",
  unreachable: "🔴",
  auth_failed: "🔴",
  unknown: "⚪",
};

export function RegionSelector() {
  const { controlPlanes, regions, selectedRegionId, setSelectedRegionId } =
    useClusterContext();

  // Only show when there are multiple regions to choose between
  if (regions.length < 2) return null;

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedRegionId(e.target.value || null);
  };

  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
      <span
        style={{
          fontSize: "0.75rem",
          color: "var(--color-text-secondary, #aaa)",
          whiteSpace: "nowrap",
        }}
      >
        Region:
      </span>
      <select
        value={selectedRegionId ?? ""}
        onChange={handleChange}
        style={{
          padding: "4px 8px",
          borderRadius: "5px",
          border: "1px solid var(--color-border, #444)",
          background: "var(--color-surface, #1e1e2e)",
          color: "var(--color-text, #e0e0e0)",
          fontSize: "0.82rem",
          cursor: "pointer",
          minWidth: "140px",
        }}
        title="Filter all views by region (All Regions = aggregate across all)"
      >
        <option value="">🌐 All Regions</option>
        {controlPlanes.map((cp) => {
          const cpRegions = regions.filter(
            (r) => r.control_plane_id === cp.id
          );
          if (cpRegions.length === 0) return null;
          return (
            <optgroup key={cp.id} label={`── ${cp.name}`}>
              {cpRegions.map((r) => {
                const dot = HEALTH_DOT[r.health_status ?? "unknown"] ?? "⚪";
                return (
                  <option key={r.id} value={r.id}>
                    {dot} {r.display_name}
                  </option>
                );
              })}
            </optgroup>
          );
        })}
      </select>
    </div>
  );
}
