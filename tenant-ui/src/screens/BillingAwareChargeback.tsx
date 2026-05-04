import { useEffect, useState } from "react";
import { 
  apiBillingAwareChargeback, 
  type BillingAwareChargeback, 
  type ChargebackVm,
  type TenantBillingStatus
} from "../lib/api";

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

function BillingStatusCard({ status }: { status: TenantBillingStatus }) {
  const isPrepaid = status.billing_model === "prepaid";
  const balanceColor = isPrepaid && status.current_balance !== undefined 
    ? status.current_balance > 100 ? "#10B981" : status.current_balance > 0 ? "#F59E0B" : "#EF4444"
    : "var(--color-text)";

  return (
    <div className="card" style={{ padding: "1rem", marginBottom: "1.5rem", border: "2px solid var(--brand-primary)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "1rem", marginBottom: ".75rem" }}>
        <div style={{ 
          fontSize: "1.1rem", 
          fontWeight: 700, 
          color: "var(--brand-primary)",
          display: "flex", 
          alignItems: "center", 
          gap: ".5rem" 
        }}>
          {isPrepaid ? "🏦 Prepaid Account" : "💳 Pay-as-you-go"}
        </div>
        {status.status_message && (
          <div style={{ 
            fontSize: ".8rem", 
            color: "var(--color-text-secondary)",
            background: "var(--color-surface-raised)",
            padding: ".25rem .5rem",
            borderRadius: ".3rem"
          }}>
            {status.status_message}
          </div>
        )}
      </div>
      
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: ".5rem" }}>
        {isPrepaid && status.current_balance !== undefined && (
          <div>
            <div style={{ fontSize: ".75rem", color: "var(--color-text-secondary)", fontWeight: 600 }}>Current Balance</div>
            <div style={{ fontSize: "1.1rem", fontWeight: 700, color: balanceColor }}>
              {fmt(status.current_balance, status.currency_code)}
            </div>
          </div>
        )}
        
        <div>
          <div style={{ fontSize: ".75rem", color: "var(--color-text-secondary)", fontWeight: 600 }}>Billing Model</div>
          <div style={{ fontSize: ".9rem", fontWeight: 600 }}>
            {isPrepaid ? "Monthly Prepaid" : "Usage-based Billing"}
          </div>
        </div>
        
        <div>
          <div style={{ fontSize: ".75rem", color: "var(--color-text-secondary)", fontWeight: 600 }}>Currency</div>
          <div style={{ fontSize: ".9rem", fontWeight: 600 }}>{status.currency_code}</div>
        </div>
        
        {isPrepaid && status.next_billing_date && (
          <div>
            <div style={{ fontSize: ".75rem", color: "var(--color-text-secondary)", fontWeight: 600 }}>Next Bill Date</div>
            <div style={{ fontSize: ".9rem", fontWeight: 600 }}>
              {new Date(status.next_billing_date).toLocaleDateString()}
            </div>
          </div>
        )}
        
        {status.sales_person && (
          <div>
            <div style={{ fontSize: ".75rem", color: "var(--color-text-secondary)", fontWeight: 600 }}>Sales Contact</div>
            <div style={{ fontSize: ".9rem", fontWeight: 600 }}>{status.sales_person}</div>
          </div>
        )}
      </div>
    </div>
  );
}

function BillingExplanationCard({ data }: { data: BillingAwareChargeback }) {
  const isPrepaid = data.billing_status.billing_model === "prepaid";
  
  return (
    <div style={{
      background: "var(--color-surface-raised)",
      border: "1px solid var(--color-border)",
      borderLeft: `3px solid ${isPrepaid ? "#3B82F6" : "#10B981"}`,
      borderRadius: ".4rem",
      padding: ".75rem 1rem",
      fontSize: ".85rem",
      marginBottom: "1.25rem",
    }}>
      <div style={{ fontWeight: 600, marginBottom: ".5rem", color: "var(--color-text)" }}>
        {isPrepaid ? "💡 Prepaid Billing Model" : "💡 Pay-as-you-go Billing Model"}
      </div>
      <div style={{ color: "var(--color-text-secondary)", lineHeight: 1.4 }}>
        {data.billing_explanation}
      </div>
      {data.cost_projection && (
        <div style={{ marginTop: ".5rem", fontWeight: 600, color: "var(--color-text)" }}>
          Monthly estimate: {fmt(data.cost_projection.monthly_estimate, data.currency)}
          {data.cost_projection.next_bill_amount && (
            <span> • Next bill: {fmt(data.cost_projection.next_bill_amount, data.currency)}</span>
          )}
          {data.cost_projection.days_until_next_bill && (
            <span> (in {data.cost_projection.days_until_next_bill} days)</span>
          )}
        </div>
      )}
    </div>
  );
}

function VmRow({ vm, max, currency, billingModel }: { 
  vm: ChargebackVm; 
  max: number; 
  currency: string;
  billingModel: "prepaid" | "pay_as_you_go";
}) {
  const [open, setOpen] = useState(false);
  const isPrepaid = billingModel === "prepaid";
  
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
        <td style={{ fontSize: ".8rem" }}>{vm.vcpus} vCPU / {vm.ram_gb} GB / {vm.disk_gb} GB disk</td>
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
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: ".4rem .8rem", fontSize: ".8rem" }}>
              <span><strong>Compute:</strong> {fmt(vm.compute_cost, currency)} 
                {isPrepaid ? " (monthly)" : ` (${fmt(vm.cost_per_hour, currency)}/hr)`}
              </span>
              <span><strong>Storage:</strong> {fmt(vm.storage_cost, currency)} ({vm.disk_gb} GB)</span>
              <span><strong>Snapshots:</strong> {fmt(vm.snapshot_cost, currency)} ({vm.snapshot_count} snapshots, {vm.snapshot_gb} GB)</span>
              <span><strong>Network:</strong> {fmt(vm.network_cost, currency)}</span>
              <span><strong>Total:</strong> {fmt(vm.estimated_cost, currency)}</span>
              <span><strong>Billing basis:</strong> {isPrepaid ? "Monthly flat rate" : "Usage-based hourly"}</span>
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

export function BillingAwareChargeback() {
  const [periodHours, setPeriodHours] = useState(720);
  const [currency, setCurrency] = useState<string>("");
  const [data, setData] = useState<BillingAwareChargeback | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = (hours: number, cur: string) => {
    setLoading(true);
    setError(null);
    apiBillingAwareChargeback(hours, cur || undefined)
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
  const isPrepaid = data?.billing_status.billing_model === "prepaid";

  return (
    <div>
      {/* Billing Status */}
      {data && (
        <>
          <BillingStatusCard status={data.billing_status} />
          <BillingExplanationCard data={data} />
        </>
      )}

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
              { 
                label: isPrepaid ? "Period Cost Estimate" : "Usage-Based Cost", 
                value: fmt(data.total_estimated_cost, data.currency), 
                accent: true 
              },
              { label: "VMs Metered", value: String(data.total_vms) },
              { 
                label: "Period", 
                value: isPrepaid ? `${data.period_label} (prorated)` : data.period_label 
              },
              { label: "Currency", value: data.currency },
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

          {/* Cost breakdown */}
          {data.cost_breakdown && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: "1rem", marginBottom: "1.5rem" }}>
              {[
                { label: "💻 Compute", value: fmt(data.cost_breakdown.compute, data.currency), color: "#3B82F6" },
                { label: "💾 Storage", value: fmt(data.cost_breakdown.storage, data.currency), color: "#10B981" },
                { label: "📸 Snapshots", value: fmt(data.cost_breakdown.snapshots, data.currency), color: "#F59E0B" },
                { label: "🌐 Network", value: fmt(data.cost_breakdown.network, data.currency), color: "#8B5CF6" },
              ].map(({ label, value, color }) => (
                <div key={label} className="card" style={{ padding: ".75rem", borderLeft: `3px solid ${color}` }}>
                  <div style={{ fontSize: ".72rem", fontWeight: 600, color: "var(--color-text-secondary)", marginBottom: ".25rem" }}>
                    {label}
                  </div>
                  <div style={{ fontSize: ".9rem", fontWeight: 600 }}>
                    {value}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Enhanced disclaimer */}
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
            <strong>⚠ {isPrepaid ? "Billing Model Note" : "Estimation only"}</strong> — {data.disclaimer}
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
                    <th>{isPrepaid ? `Monthly Cost (${data.period_label} view)` : `Estimated cost (${data.period_label})`}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.vms.map((vm) => (
                    <VmRow 
                      key={vm.vm_id} 
                      vm={vm} 
                      max={maxCost} 
                      currency={data.currency}
                      billingModel={data.billing_status.billing_model}
                    />
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