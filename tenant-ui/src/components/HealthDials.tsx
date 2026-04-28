/**
 * HealthDials.tsx — Three circular SVG dials showing Efficiency, Stability,
 * and Capacity Runway scores for the current tenant / project.
 *
 * Each dial renders a full-circle track + a coloured arc indicating the score (0–100).
 */

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
  quota_configured?: boolean;  // false = no quota data; null/undefined treated as unknown
  last_computed: string;
}

interface DialProps {
  label: string;
  value: number | null;  // null = no data: renders empty grey ring
  sublabel?: string;
  color?: string;
  tooltip?: string;
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

function Dial({ label, value, sublabel, color, tooltip }: DialProps) {
  const pct    = value == null ? 0 : Math.min(100, Math.max(0, value));
  const offset = CIRCUMF - (pct / 100) * CIRCUMF;
  const fill   = value == null ? "rgba(255,255,255,0.25)" : (color ?? scoreColor(pct));

  return (
    <div title={tooltip} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "0.5rem", cursor: tooltip ? "help" : undefined }}>
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
          {value == null ? "\u2014" : Math.round(pct)}
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
  const runwayScore: number | null = health.capacity_runway_days == null
    ? null
    : Math.min(100, (health.capacity_runway_days / 90) * 100); // 90 days = 100%

  const runwaySub = health.capacity_runway_days == null
    ? (health.quota_configured === false ? "no quota configured" : "usage stable")
    : `${health.capacity_runway_days}d until ${health.capacity_runway_resource ?? "limit"}`;

  const stabSub = health.open_critical || health.open_high || health.open_medium
    ? `${health.open_critical}c / ${health.open_high}h / ${health.open_medium}m open`
    : "no open issues";

  // Contextual guidance messages shown below the dials when scores are concerning
  const notices: string[] = [];
  if (health.efficiency_score !== null && health.efficiency_score < 40) {
    notices.push(
      `Efficiency ${health.efficiency_score}/100 (${health.efficiency_classification}): Your VMs are using a small fraction of their allocated vCPU and RAM. Consider right-sizing to a smaller flavor, or consolidating idle workloads.`
    );
  }
  if (health.capacity_runway_days !== null && health.capacity_runway_days < 14) {
    notices.push(
      health.capacity_runway_days === 0
        ? `Capacity Runway: One or more of your project quotas is at or near its limit right now. Contact your cloud administrator to increase your quota before new resources can be created.`
        : `Capacity Runway: At your current growth rate, a quota will be exhausted in ${health.capacity_runway_days} day${health.capacity_runway_days === 1 ? "" : "s"}. Contact your administrator to request a quota increase.`
    );
  }
  if (health.capacity_runway_days === null && health.quota_configured === false) {
    notices.push(
      `Capacity Runway: No resource quotas are configured for your project. Contact your cloud administrator if you expected quota limits to be set.`
    );
  }

  return (
    <div>
      <div style={{
        display: "flex",
        gap: "2.5rem",
        justifyContent: "center",
        padding: "1.25rem 1.5rem",
        background: "rgba(0,0,0,0.25)",
        borderRadius: notices.length ? "10px 10px 0 0" : "10px",
        flexWrap: "wrap",
      }}>
        <Dial
          label="Efficiency"
          value={health.efficiency_score}
          sublabel={health.efficiency_classification}
          tooltip="Resource efficiency score (0–100). Measures how well your VMs use their allocated CPU and memory over the last 7 days. Higher is better. Hover over the score to learn more."
        />
        <Dial
          label="Stability"
          value={health.stability_score}
          sublabel={stabSub}
          tooltip="Service stability score (0–100). Starts at 100 and is reduced for each unresolved critical, high, or medium platform insight. A score of 100 means no open issues."
        />
        <Dial
          label="Capacity Runway"
          value={runwayScore}
          sublabel={runwaySub}
          color={runwayScore == null ? undefined : (runwayScore < 30 ? "#ef4444" : runwayScore < 60 ? "#f97316" : "#22c55e")}
          tooltip="Estimated days until a project quota reaches 90% of its limit, based on your current resource growth trend. 0 means a quota is at or near its limit now."
        />
      </div>
      {notices.length > 0 && (
        <div style={{
          background: "rgba(0,0,0,0.18)",
          borderRadius: "0 0 10px 10px",
          padding: "0.75rem 1.25rem",
          display: "flex",
          flexDirection: "column",
          gap: "0.4rem",
        }}>
          {notices.map((msg, i) => (
            <div key={i} style={{ fontSize: "0.78rem", color: "rgba(255,255,255,0.7)", lineHeight: 1.5 }}>
              ⚠️ {msg}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default HealthDials;

