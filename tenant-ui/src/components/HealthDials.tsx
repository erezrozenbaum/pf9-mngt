/**
 * HealthDials.tsx — Three circular SVG dials showing Efficiency, Stability,
 * and Capacity Runway scores for the current tenant / project.
 *
 * Each dial renders a full-circle track + a coloured arc indicating the score (0–100).
 */

import React from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ClientHealth {
  tenant_id: string;
  efficiency_score: number;              // 0–100
  efficiency_classification: string;     // 'excellent' | 'good' | 'fair' | 'poor' | 'unknown'
  stability_score: number;               // 0–100
  open_critical: number;
  open_high: number;
  open_medium: number;
  capacity_runway_days: number | null;
  capacity_runway_resource: string | null;
  last_computed: string;
}

interface DialProps {
  label: string;
  value: number;     // 0–100
  sublabel?: string;
  color?: string;
}

// ---------------------------------------------------------------------------
// Single dial
// ---------------------------------------------------------------------------

const DIAL_SIZE   = 120;
const STROKE_W    = 10;
const RADIUS      = (DIAL_SIZE - STROKE_W) / 2;
const CIRCUMF     = 2 * Math.PI * RADIUS;

function scoreColor(v: number): string {
  if (v >= 80) return "#22c55e"; // green
  if (v >= 60) return "#eab308"; // yellow
  if (v >= 40) return "#f97316"; // orange
  return "#ef4444";              // red
}

function Dial({ label, value, sublabel, color }: DialProps) {
  const pct    = Math.min(100, Math.max(0, value));
  const offset = CIRCUMF - (pct / 100) * CIRCUMF;
  const fill   = color ?? scoreColor(pct);

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "0.5rem" }}>
      <svg width={DIAL_SIZE} height={DIAL_SIZE} viewBox={`0 0 ${DIAL_SIZE} ${DIAL_SIZE}`}>
        {/* Track */}
        <circle
          cx={DIAL_SIZE / 2}
          cy={DIAL_SIZE / 2}
          r={RADIUS}
          fill="none"
          stroke="rgba(255,255,255,0.1)"
          strokeWidth={STROKE_W}
        />
        {/* Arc */}
        <circle
          cx={DIAL_SIZE / 2}
          cy={DIAL_SIZE / 2}
          r={RADIUS}
          fill="none"
          stroke={fill}
          strokeWidth={STROKE_W}
          strokeLinecap="round"
          strokeDasharray={`${CIRCUMF}`}
          strokeDashoffset={offset}
          transform={`rotate(-90 ${DIAL_SIZE / 2} ${DIAL_SIZE / 2})`}
          style={{ transition: "stroke-dashoffset 0.6s ease" }}
        />
        {/* Centre text */}
        <text
          x={DIAL_SIZE / 2}
          y={DIAL_SIZE / 2 + 6}
          textAnchor="middle"
          fill={fill}
          fontSize="22"
          fontWeight="700"
          fontFamily="inherit"
        >
          {Math.round(pct)}
        </text>
      </svg>
      <div style={{ fontWeight: 600, fontSize: "0.85rem", textAlign: "center" }}>{label}</div>
      {sublabel && (
        <div style={{ fontSize: "0.72rem", color: "rgba(255,255,255,0.55)", textAlign: "center" }}>
          {sublabel}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// HealthDials row
// ---------------------------------------------------------------------------

interface Props {
  health: ClientHealth;
}

export function HealthDials({ health }: Props) {
  const runwayScore = health.capacity_runway_days == null
    ? 0
    : Math.min(100, (health.capacity_runway_days / 90) * 100); // 90 days = 100%

  const runwaySub = health.capacity_runway_days == null
    ? "no data"
    : `${health.capacity_runway_days}d until ${health.capacity_runway_resource ?? "limit"}`;

  const stabSub = health.open_critical || health.open_high || health.open_medium
    ? `${health.open_critical}c / ${health.open_high}h / ${health.open_medium}m open`
    : "no open issues";

  return (
    <div style={{
      display: "flex",
      gap: "2.5rem",
      justifyContent: "center",
      padding: "1.25rem 1.5rem",
      background: "rgba(0,0,0,0.25)",
      borderRadius: "10px",
      flexWrap: "wrap",
    }}>
      <Dial
        label="Efficiency"
        value={health.efficiency_score}
        sublabel={health.efficiency_classification}
      />
      <Dial
        label="Stability"
        value={health.stability_score}
        sublabel={stabSub}
      />
      <Dial
        label="Capacity Runway"
        value={runwayScore}
        sublabel={runwaySub}
        color={runwayScore < 30 ? "#ef4444" : runwayScore < 60 ? "#f97316" : "#22c55e"}
      />
    </div>
  );
}

export default HealthDials;
