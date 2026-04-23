import { useEffect, useState } from "react";
import { apiChargeback, type ChargebackSummary, type ChargebackVm } from "../lib/api";

const CURRENCIES = ["USD", "EUR", "GBP", "ILS", "AUD", "CAD", "CHF", "JPY"];
const PERIODS: Array<{ label: string; hours: number }> = [
  { label: "Last 24 hours", hours: 24 },
  { label: "Last 7 days",   hours: 168 },
  { label: "Last 30 days",  hours: 720 },
  { label: "Last 90 days",  hours: 2160 },
];

function fmt(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${currency} ${value.toFixed(2)}`;
  }
}

function CostBar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.max(2, (value / max) * 100) : 0;
  return (
    <div className="progress-track" style={{ height: "6px", minWidth: "60px", flex: 1 }}>
      <div className="progress-fill" style={{ width: `${pct}%`, background: "var(--brand-primary)" }} />
    </div>
  );
}

function VmRow({ vm, max, currency }: { vm: ChargebackVm; max: number; currency: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr
        style={{ cursor: "pointer" }}
        onClick={() => setOpen((o) => !o)}
        title="Click for details"
      >
        <td style={{ fontWeight: 500 }}>{vm.vm_name}</td>
        <td style={{ color: "var(--color-text-secondary)", fontSize: ".8rem" }}>{vm.project_name}</td>
        <td style={{ color: "var(--color-text-secondary)", fontSize: ".8rem" }}>{vm.flavor}</td>
        <td style={{ fontSize: ".8rem" }}>{vm.vcpus} vCPU / {vm.ram_gb} GB</td>
        <td>
          <div style={{ display: "flex", alignItems: "center", gap: ".5rem" }}>
            <CostBar value={vm.estimated_cost} max={max} />
            <span style={{ fontWeight: 600, minWidth: "5.5rem", textAlign: "right" }}>
              {fmt(vm.estimated_cost, currency)}
            </span>
          </div>
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={5} style={{ background: "var(--color-surface-raised)", padding: ".6rem 1rem" }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: ".4rem .8rem", fontSize: ".8rem" }}>
              <span><strong>Cost/hr:</strong> {fmt(vm.cost_per_hour, currency)}</span>
              <span><strong>Pricing basis:</strong> {vm.pricing_basis}</span>
              {vm.last_metering && (
                <span><strong>Last metered:</strong> {new Date(vm.last_metering).toLocaleString()}</span>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export function Chargeback() {
  const [periodHours, setPeriodHours] = useState(720);
  const [currency, setCurrency] = useState<string>("");
  const [data, setData] = useState<ChargebackSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = (hours: number, cur: string) => {
    setLoading(true);
    setError(null);
    apiChargeback(hours, cur || undefined)
      .then((d) => {
        setData(d);
        if (!cur) setCurrency(d.currency);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(periodHours, currency); }, []);

  const handlePeriod = (h: number) => { setPeriodHours(h); load(h, currency); };
  const handleCurrency = (c: string) => { setCurrency(c); load(periodHours, c); };

  const maxCost = data ? Math.max(...data.vms.map((v) => v.estimated_cost), 0.01) : 0.01;

  return (
    <div>
      {/* Controls */}
      <div style={{ display: "flex", gap: ".75rem", marginBottom: "1.25rem", flexWrap: "wrap", alignItems: "center" }}>
        <div style={{ display: "flex", gap: ".4rem" }}>
          {PERIODS.map((p) => (
            <button
              key={p.hours}
              className={`btn ${periodHours === p.hours ? "btn-primary" : "btn-secondary"}`}
              style={{ padding: ".35rem .75rem", fontSize: ".8rem" }}
              onClick={() => handlePeriod(p.hours)}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: ".4rem", marginLeft: "auto" }}>
          <label style={{ fontSize: ".8rem", color: "var(--color-text-secondary)", fontWeight: 600 }}>Currency:</label>
          <select
            className="select"
            style={{ fontSize: ".8rem", padding: ".3rem .5rem" }}
            value={currency}
            onChange={(e) => handleCurrency(e.target.value)}
          >
            {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
      </div>

      {loading && <div className="empty-state"><span className="loading-spinner" /></div>}
      {error   && <div className="error-banner">{error}</div>}

      {!loading && !error && data && (
        <>
          {/* Summary cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: "1rem", marginBottom: "1.5rem" }}>
            {[
              { label: "Total Estimated Cost", value: fmt(data.total_estimated_cost, data.currency), accent: true },
              { label: "VMs Metered",          value: String(data.total_vms) },
              { label: "Period",               value: data.period_label },
              { label: "Currency",             value: data.currency },
            ].map(({ label, value, accent }) => (
              <div key={label} className="card" style={{ padding: "1rem" }}>
                <div style={{ fontSize: ".72rem", fontWeight: 600, textTransform: "uppercase", letterSpacing: ".04em", color: "var(--color-text-secondary)", marginBottom: ".35rem" }}>
                  {label}
                </div>
                <div style={{ fontSize: accent ? "1.25rem" : "1rem", fontWeight: 700, color: accent ? "var(--brand-primary)" : "var(--color-text)" }}>
                  {value}
                </div>
              </div>
            ))}
          </div>

          {/* Disclaimer */}
          <div style={{
            background: "var(--color-surface-raised)",
            border: "1px solid var(--color-border)",
            borderLeft: "3px solid var(--color-warning)",
            borderRadius: ".4rem",
            padding: ".6rem .9rem",
            fontSize: ".8rem",
            color: "var(--color-text-secondary)",
            marginBottom: "1.25rem",
          }}>
            <strong>⚠ Estimation only</strong> — {data.disclaimer}
            {data.pricing_basis_note && (
              <div style={{ marginTop: ".25rem" }}>{data.pricing_basis_note}</div>
            )}
          </div>

          {/* VM table */}
          {data.vms.length === 0 ? (
            <div className="empty-state">No metering data for this period.</div>
          ) : (
            <div className="card table-wrap" style={{ padding: 0 }}>
              <table>
                <thead>
                  <tr>
                    <th>VM</th>
                    <th>Project</th>
                    <th>Flavor</th>
                    <th>Resources</th>
                    <th>Estimated cost ({data.period_label})</th>
                  </tr>
                </thead>
                <tbody>
                  {data.vms.map((vm) => (
                    <VmRow key={vm.vm_id} vm={vm} max={maxCost} currency={data.currency} />
                  ))}
                  <tr style={{ borderTop: "2px solid var(--color-border)", fontWeight: 700 }}>
                    <td colSpan={4} style={{ textAlign: "right", paddingRight: "1rem" }}>Total</td>
                    <td style={{ textAlign: "right", paddingRight: ".6rem" }}>{fmt(data.total_estimated_cost, data.currency)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
