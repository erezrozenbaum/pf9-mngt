/**
 * Pure SVG chart primitives — no external dependencies.
 *
 * Exports:
 *   <BarChart>    — daily snapshot success/fail stacked bars
 *   <DonutChart>  — VM status ring
 *   <QuotaBar>    — single horizontal usage bar
 */

import type { CSSProperties } from "react";

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function clamp(v: number, min: number, max: number) {
  return Math.max(min, Math.min(max, v));
}

// ─────────────────────────────────────────────────────────────────────────────
// BarChart — stacked daily bars (success/fail)
// ─────────────────────────────────────────────────────────────────────────────

export interface BarDay {
  label: string;   // e.g. "Apr 14"
  success: number;
  fail: number;
}

interface BarChartProps {
  data: BarDay[];
  height?: number;
  style?: CSSProperties;
}

export function BarChart({ data, height = 120, style }: BarChartProps) {
  const W = 100;                  // SVG viewBox width (%) — we use preserveAspectRatio
  const BAR_GAP = 1;
  const n = data.length;
  if (n === 0) return null;

  const barW = (W - BAR_GAP * (n - 1)) / n;
  const maxVal = Math.max(...data.map((d) => d.success + d.fail), 1);

  const toY = (v: number) => ((maxVal - v) / maxVal) * 100;
  const toH = (v: number) => (v / maxVal) * 100;

  return (
    <svg
      viewBox={`0 0 100 100`}
      preserveAspectRatio="none"
      style={{ width: "100%", height, display: "block", overflow: "visible", ...style }}
      role="img"
      aria-label="Snapshot activity chart"
    >
      {data.map((d, i) => {
        const x = i * (barW + BAR_GAP);
        const failH = toH(d.fail);
        const sucH = toH(d.success);
        const failY = toY(d.fail + d.success);
        const sucY = failY + failH;
        return (
          <g key={d.label}>
            {/* fail segment (top, red) */}
            {d.fail > 0 && (
              <rect x={x} y={failY} width={barW} height={failH}
                fill="var(--color-error)" opacity={0.85} rx={0.5}>
                <title>{d.label} — {d.fail} failed</title>
              </rect>
            )}
            {/* success segment (bottom, green) */}
            {d.success > 0 && (
              <rect x={x} y={sucY} width={barW} height={sucH}
                fill="var(--color-success)" opacity={0.85} rx={0.5}>
                <title>{d.label} — {d.success} successful</title>
              </rect>
            )}
          </g>
        );
      })}
    </svg>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// DonutChart — VM status ring
// ─────────────────────────────────────────────────────────────────────────────

export interface DonutSlice {
  label: string;
  value: number;
  color: string;
}

interface DonutChartProps {
  slices: DonutSlice[];
  size?: number;
  thickness?: number;
  centerLabel?: string;
  centerSub?: string;
}

export function DonutChart({ slices, size = 100, thickness = 18, centerLabel, centerSub }: DonutChartProps) {
  const R = 40;
  const cx = 50;
  const cy = 50;
  const circumference = 2 * Math.PI * R;
  const total = slices.reduce((s, d) => s + d.value, 0);
  if (total === 0) return null;

  let offset = 0;
  const segments = slices.map((s) => {
    const frac = s.value / total;
    const dash = frac * circumference;
    const gap = circumference - dash;
    const startOffset = offset;
    offset += dash;
    return { ...s, dash, gap, startOffset };
  });

  return (
    <svg viewBox="0 0 100 100" width={size} height={size} style={{ display: "block" }}>
      {segments.map((seg, i) => (
        <circle
          key={i}
          cx={cx} cy={cy} r={R}
          fill="none"
          stroke={seg.color}
          strokeWidth={thickness}
          strokeDasharray={`${seg.dash} ${seg.gap}`}
          strokeDashoffset={-seg.startOffset + circumference / 4}
          style={{ transition: "stroke-dasharray .4s" }}
        >
          <title>{seg.label}: {seg.value}</title>
        </circle>
      ))}
      {/* inner white circle to create donut hole */}
      <circle cx={cx} cy={cy} r={R - thickness / 2 - 1} fill="var(--color-surface)" />
      {centerLabel && (
        <text x={cx} y={cy - (centerSub ? 4 : 0)} textAnchor="middle" dominantBaseline="middle"
          fontSize={centerSub ? 13 : 16} fontWeight="700" fill="var(--color-text)">
          {centerLabel}
        </text>
      )}
      {centerSub && (
        <text x={cx} y={cy + 10} textAnchor="middle" dominantBaseline="middle"
          fontSize={8} fill="var(--color-text-secondary)">
          {centerSub}
        </text>
      )}
    </svg>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// QuotaBar — single horizontal usage bar with label
// ─────────────────────────────────────────────────────────────────────────────

interface QuotaBarProps {
  label: string;
  used: number;
  limit: number;
  unit?: string;
}

export function QuotaBar({ label, used, limit, unit = "" }: QuotaBarProps) {
  const pct = limit > 0 ? clamp((used / limit) * 100, 0, 100) : 0;
  const unlimited = limit === -1;
  const color =
    unlimited ? "var(--color-info)" :
    pct >= 90 ? "var(--color-error)" :
    pct >= 75 ? "var(--color-warning)" :
    "var(--color-success)";

  const fmt = (v: number) =>
    unit === "GB" ? `${v} GB` :
    unit === "MB" ? v >= 1024 ? `${(v / 1024).toFixed(0)} GB` : `${v} MB` :
    String(v);

  return (
    <div style={{ marginBottom: ".6rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: ".8rem", marginBottom: ".2rem" }}>
        <span style={{ color: "var(--color-text)", fontWeight: 500 }}>{label}</span>
        <span style={{ color: "var(--color-text-secondary)" }}>
          {unlimited ? `${fmt(used)} / ∞` : `${fmt(used)} / ${fmt(limit)}`}
        </span>
      </div>
      <div style={{ height: "6px", background: "var(--color-border)", borderRadius: "3px", overflow: "hidden" }}>
        <div style={{
          height: "100%",
          width: unlimited ? "0%" : `${pct}%`,
          background: color,
          borderRadius: "3px",
          transition: "width .4s",
        }} />
      </div>
    </div>
  );
}
