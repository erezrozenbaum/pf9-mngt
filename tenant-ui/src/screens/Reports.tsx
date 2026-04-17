import { useEffect, useState } from "react";
import { apiTenantReports, apiDownloadTenantReport, type TenantReport } from "../lib/api";

// ── Category icon ─────────────────────────────────────────────────────────

function categoryIcon(cat: string): string {
  const c = cat.toLowerCase();
  if (c === "protection") return "🛡";
  if (c === "recovery")   return "🔄";
  if (c === "inventory")  return "🖥";
  if (c === "storage")    return "💾";
  if (c === "audit")      return "📋";
  return "📊";
}

// ── Main component ────────────────────────────────────────────────────────

export function Reports() {
  const [reports, setReports] = useState<TenantReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  // Optional date range filters
  const today = new Date().toISOString().slice(0, 10);
  const thirtyDaysAgo = new Date(Date.now() - 30 * 24 * 3600 * 1000).toISOString().slice(0, 10);
  const [fromDate, setFromDate] = useState(thirtyDaysAgo);
  const [toDate, setToDate] = useState(today);

  useEffect(() => {
    let active = true;
    apiTenantReports()
      .then((r) => { if (active) setReports(r); })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : "Failed to load"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const handleDownload = async (report: TenantReport) => {
    setDownloading(report.name);
    setDownloadError(null);
    try {
      const blob = await apiDownloadTenantReport(report.name, { from_date: fromDate, to_date: toDate });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${report.name}_${fromDate}_${toDate}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e: unknown) {
      setDownloadError(e instanceof Error ? e.message : "Download failed");
    } finally {
      setDownloading(null);
    }
  };

  if (loading) return <div className="empty-state"><span className="loading-spinner" /></div>;
  if (error)   return <div className="error-banner">{error}</div>;

  const categories = [...new Set(reports.map((r) => r.category))].sort();

  return (
    <div>
      {/* Date range filter */}
      <div className="filter-bar" style={{ marginBottom: "1.25rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: ".75rem", flexWrap: "wrap" }}>
          <label style={{ display: "flex", alignItems: "center", gap: ".4rem", fontSize: ".875rem" }}>
            <span style={{ color: "var(--color-text-secondary)" }}>From:</span>
            <input
              type="date"
              className="input"
              style={{ padding: ".3rem .5rem", fontSize: ".875rem" }}
              value={fromDate}
              max={toDate}
              onChange={(e) => setFromDate(e.target.value)}
            />
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: ".4rem", fontSize: ".875rem" }}>
            <span style={{ color: "var(--color-text-secondary)" }}>To:</span>
            <input
              type="date"
              className="input"
              style={{ padding: ".3rem .5rem", fontSize: ".875rem" }}
              value={toDate}
              min={fromDate}
              max={today}
              onChange={(e) => setToDate(e.target.value)}
            />
          </label>
        </div>
      </div>

      {downloadError && <div className="error-banner" style={{ marginBottom: "1rem" }}>{downloadError}</div>}

      {categories.map((cat) => (
        <div key={cat} style={{ marginBottom: "1.5rem" }}>
          <div className="section-title">{categoryIcon(cat)} {cat}</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: "1rem" }}>
            {reports.filter((r) => r.category === cat).map((report) => (
              <div key={report.name} className="card" style={{ display: "flex", flexDirection: "column", gap: ".5rem" }}>
                <div style={{ fontWeight: 600, fontSize: ".9rem" }}>{report.display_name}</div>
                <div style={{ fontSize: ".8125rem", color: "var(--color-text-secondary)", lineHeight: 1.5, flex: 1 }}>
                  {report.description}
                </div>
                <button
                  className="btn btn-primary"
                  style={{ alignSelf: "flex-start", marginTop: ".25rem" }}
                  disabled={downloading === report.name}
                  onClick={() => handleDownload(report)}
                >
                  {downloading === report.name
                    ? <span className="loading-spinner" />
                    : "⬇ Download CSV"
                  }
                </button>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
