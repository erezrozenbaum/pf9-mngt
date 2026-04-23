import { useEffect, useState } from "react";
import {
  apiRunbooks, apiRunbook, apiExecuteRunbook, apiRunbookExecutions, apiVms,
  type Runbook, type RunbookExecution, type Vm,
} from "../lib/api";

// ── Helpers ─────────────────────────────────────────────────────────────────

function RiskBadge({ level }: { level: string | undefined }) {
  const l = (level ?? "low").toLowerCase();
  if (l === "low")    return <span className="badge badge-green">Low risk</span>;
  if (l === "medium") return <span className="badge badge-amber">Medium risk</span>;
  if (l === "high")   return <span className="badge badge-red">High risk</span>;
  return <span className="badge badge-grey">{level}</span>;
}

function statusBadge(s: string | undefined) {
  const l = (s ?? "").toLowerCase();
  if (l === "completed")  return <span className="badge badge-green">Completed</span>;
  if (l === "failed")     return <span className="badge badge-red">Failed</span>;
  if (l === "executing")  return <span className="badge badge-amber">Running…</span>;
  if (l === "approved")   return <span className="badge badge-blue">Queued</span>;
  return <span className="badge badge-grey">{s}</span>;
}

function categoryIcon(cat: string): string {
  const c = cat.toLowerCase();
  if (c.includes("trouble"))  return "🔍";
  if (c.includes("recovery")) return "🔄";
  if (c.includes("restore"))  return "📋";
  if (c.includes("incident")) return "⚠️";
  return "📖";
}

// ── Execution result viewer ──────────────────────────────────────────────────

function ExecutionResultPanel({ exec, onClose }: { exec: RunbookExecution; onClose: () => void }) {
  const result = exec.result ?? {};
  const items_found    = exec.items_found;
  const items_actioned = exec.items_actioned;
  const inner = result as Record<string, unknown> | undefined;

  return (
    <>
      <div className="side-panel-overlay" onClick={onClose} />
      <aside className="side-panel" aria-label="Execution result">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: ".75rem", marginBottom: "1.25rem" }}>
          <div style={{ flex: 1 }}>
            <h2 style={{ fontSize: "1rem", fontWeight: 700 }}>{exec.display_name}</h2>
            <div style={{ display: "flex", gap: ".5rem", marginTop: ".4rem", flexWrap: "wrap" }}>
              {statusBadge(exec.status)}
              {exec.dry_run && <span className="badge badge-amber">Dry run</span>}
              <RiskBadge level={exec.risk_level} />
            </div>
          </div>
          <button className="btn btn-secondary" onClick={onClose} style={{ padding: ".35rem .65rem", flexShrink: 0 }}>✕</button>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: ".5rem 1rem", marginBottom: "1.25rem" }}>
          {[
            ["Triggered", exec.triggered_at ? new Date(exec.triggered_at).toLocaleString() : "—"],
            ["Completed", exec.completed_at ? new Date(exec.completed_at).toLocaleString() : "—"],
            ["Items found", String(items_found)],
            ["Items actioned", String(items_actioned)],
          ].map(([k, v]) => (
            <div key={k}>
              <div style={{ fontSize: ".7rem", fontWeight: 600, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: ".04em" }}>{k}</div>
              <div style={{ fontSize: ".875rem", fontWeight: 500 }}>{v}</div>
            </div>
          ))}
        </div>

        {exec.error_message && (
          <div className="error-banner" style={{ marginBottom: "1rem" }}>{exec.error_message}</div>
        )}

        {inner && Object.keys(inner).length > 0 && (
          <div>
            <div className="section-title">Results</div>
            {Object.entries(inner).map(([k, v]) => (
              <div key={k} style={{ marginBottom: ".75rem" }}>
                <div style={{ fontSize: ".8rem", fontWeight: 600, textTransform: "capitalize", marginBottom: ".3rem" }}>
                  {k.replace(/_/g, " ")}
                </div>
                {Array.isArray(v) ? (
                  v.length === 0 ? (
                    <div style={{ color: "var(--color-text-secondary)", fontSize: ".8rem" }}>None</div>
                  ) : (
                    <div style={{ maxHeight: "240px", overflowY: "auto" }}>
                      {v.map((item, i) => (
                        <div key={i} style={{ fontSize: ".8rem", padding: ".35rem .5rem", background: "var(--color-surface-raised)", borderRadius: ".3rem", marginBottom: ".25rem" }}>
                          {typeof item === "object" ? (
                            <div style={{ display: "flex", flexWrap: "wrap", gap: ".4rem" }}>
                              {Object.entries(item as Record<string, unknown>).slice(0, 6).map(([ik, iv]) => (
                                <span key={ik} style={{ color: "var(--color-text-secondary)" }}>
                                  <strong>{ik}:</strong> {String(iv)}
                                </span>
                              ))}
                            </div>
                          ) : String(item)}
                        </div>
                      ))}
                    </div>
                  )
                ) : v !== null && typeof v === "object" ? (
                  // Plain nested object — render as a compact key-value list
                  <div style={{ fontSize: ".8rem", border: "1px solid var(--color-border)", borderRadius: ".3rem", overflow: "hidden" }}>
                    {Object.entries(v as Record<string, unknown>).map(([ik, iv], idx) => {
                      const ivStr = iv !== null && iv !== undefined ? String(iv) : "—";
                      const isUrl = ivStr.startsWith("http://") || ivStr.startsWith("https://");
                      return (
                        <div key={ik} style={{
                          display: "flex", gap: ".5rem", padding: ".3rem .6rem",
                          background: idx % 2 === 0 ? "var(--color-surface-raised)" : "transparent",
                        }}>
                          <span style={{ fontWeight: 600, color: "var(--color-text-secondary)", minWidth: "9rem", flexShrink: 0, textTransform: "capitalize" }}>
                            {ik.replace(/_/g, " ")}
                          </span>
                          {isUrl
                            ? <a href={ivStr} target="_blank" rel="noopener noreferrer" style={{ color: "var(--brand-primary)", wordBreak: "break-all" }}>{ivStr}</a>
                            : <span style={{ wordBreak: "break-word" }}>{ivStr}</span>}
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div style={{ fontSize: ".85rem" }}>{String(v ?? "—")}</div>
                )}
              </div>
            ))}
          </div>
        )}
      </aside>
    </>
  );
}

// ── Execute dialog ─────────────────────────────────────────────────────────

function ExecuteDialog({
  runbook,
  vms,
  onClose,
  onDone,
}: {
  runbook: Runbook;
  vms: Vm[];
  onClose: () => void;
  onDone: (exec: RunbookExecution) => void;
}) {
  const [dryRun, setDryRun] = useState(runbook.risk_level.toLowerCase() !== "low");
  const [params, setParams] = useState<Record<string, string>>({});
  const [selectedVmIds, setSelectedVmIds] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Determine VM-selector params from the schema.
  // Single VM: any property with x-lookup="vms", or conventionally named vm_id / vm_name / server_id.
  // Multi VM:  any property with x-lookup="vms_multi" (list of UUIDs).
  const schema = runbook.parameters_schema ?? {};
  const props = (schema.properties ?? {}) as Record<string, Record<string, unknown>>;
  const vmPropEntry = Object.entries(props).find(
    ([k, def]) => def["x-lookup"] === "vms" || k === "vm_id" || k === "vm_name" || k === "server_id"
  );
  const vmsMultiEntry = Object.entries(props).find(([, def]) => def["x-lookup"] === "vms_multi");
  const needsVm = Boolean(vmPropEntry);
  const vmParamKey = vmPropEntry ? vmPropEntry[0] : "vm_id";
  const vmsMultiKey = vmsMultiEntry ? vmsMultiEntry[0] : null;
  const vmsMultiDef = vmsMultiEntry ? vmsMultiEntry[1] : null;
  const extraParams = Object.entries(props).filter(
    ([k]) => k !== vmParamKey && k !== vmsMultiKey && k !== "target_project" && k !== "region_id"
  );

  const handleRun = async () => {
    setRunning(true);
    setErr(null);
    try {
      const finalParams: Record<string, unknown> = {};
      Object.entries(params).forEach(([k, v]) => { if (v) finalParams[k] = v; });
      // Multi-VM param: send array of UUIDs (empty = all VMs in project, per engine docs)
      if (vmsMultiKey && selectedVmIds.length > 0) {
        finalParams[vmsMultiKey] = selectedVmIds;
      }
      const result = await apiExecuteRunbook(runbook.name, finalParams, dryRun);
      onDone(result);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Execution failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <>
      <div className="side-panel-overlay" onClick={() => { if (!running) onClose(); }} />
      <aside className="side-panel" aria-label="Execute runbook">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: ".75rem", marginBottom: "1.25rem" }}>
          <div>
            <h2 style={{ fontSize: "1rem", fontWeight: 700 }}>Execute: {runbook.display_name}</h2>
            <div style={{ display: "flex", gap: ".5rem", marginTop: ".4rem" }}>
              <RiskBadge level={runbook.risk_level} />
            </div>
          </div>
          <button className="btn btn-secondary" onClick={onClose} disabled={running} style={{ padding: ".35rem .65rem", flexShrink: 0 }}>✕</button>
        </div>

        <p style={{ fontSize: ".875rem", color: "var(--color-text-secondary)", marginBottom: "1.25rem" }}>
          {runbook.description}
        </p>

        {needsVm && (
          <div style={{ marginBottom: "1rem" }}>
            <label style={{ fontSize: ".85rem", fontWeight: 600 }}>
              Target VM *
              <select className="select" value={params[vmParamKey] ?? ""}
                onChange={(e) => setParams((p) => ({ ...p, [vmParamKey]: e.target.value }))}>
                <option value="">— Select VM —</option>
                {/* Always send vm_id (UUID) regardless of the param key name */}
                {vms.map((v) => <option key={v.vm_id} value={v.vm_id}>{v.vm_name}</option>)}
              </select>
            </label>
          </div>
        )}

        {vmsMultiKey && (
          <div style={{ marginBottom: "1rem" }}>
            <div style={{ fontSize: ".85rem", fontWeight: 600, marginBottom: ".3rem" }}>
              {String(vmsMultiDef?.title ?? vmsMultiKey.replace(/_/g, " ")).replace(/\b\w/g, (c) => c.toUpperCase())}
            </div>
            {!!vmsMultiDef?.description && (
              <div style={{ fontSize: ".75rem", color: "var(--color-text-secondary)", marginBottom: ".4rem" }}>
                {String(vmsMultiDef.description)}
              </div>
            )}
            <div style={{
              maxHeight: "180px", overflowY: "auto", border: "1px solid var(--color-border)",
              borderRadius: ".35rem", padding: ".4rem .6rem",
            }}>
              {vms.length === 0
                ? <div style={{ fontSize: ".8rem", color: "var(--color-text-secondary)" }}>No VMs found</div>
                : vms.map((v) => (
                  <label key={v.vm_id} style={{ display: "flex", alignItems: "center", gap: ".5rem", fontSize: ".8125rem", padding: ".2rem 0", cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      checked={selectedVmIds.includes(v.vm_id)}
                      onChange={(e) => setSelectedVmIds((prev) =>
                        e.target.checked ? [...prev, v.vm_id] : prev.filter((id) => id !== v.vm_id)
                      )}
                    />
                    {v.vm_name}
                  </label>
                ))}
            </div>
            {vms.length > 0 && (
              <div style={{ fontSize: ".72rem", color: "var(--color-text-secondary)", marginTop: ".25rem" }}>
                {selectedVmIds.length === 0 ? "None selected — engine will analyse all VMs in project" : `${selectedVmIds.length} VM${selectedVmIds.length !== 1 ? "s" : ""} selected`}
              </div>
            )}
          </div>
        )}

        {extraParams.map(([k, def]) => (
          <div key={k} style={{ marginBottom: "1rem" }}>
            <label style={{ fontSize: ".85rem", fontWeight: 600 }}>
              {String((def as Record<string, unknown>).title ?? k.replace(/_/g, " ")).replace(/\b\w/g, (c) => c.toUpperCase())}
              {Boolean((def as Record<string, unknown>).description) && (
                <div style={{ fontWeight: 400, color: "var(--color-text-secondary)", fontSize: ".75rem", marginBottom: ".25rem" }}>
                  {String((def as Record<string, unknown>).description)}
                </div>
              )}
              <input className="input" type={(def as Record<string, unknown>).type === "number" ? "number" : "text"}
                placeholder={String((def as Record<string, unknown>).default ?? "")}
                value={params[k] ?? ""}
                onChange={(e) => setParams((p) => ({ ...p, [k]: e.target.value }))} />
            </label>
          </div>
        ))}

        {runbook.supports_dry_run && (
          <label style={{ display: "flex", alignItems: "center", gap: ".5rem", fontSize: ".875rem", marginBottom: "1rem", cursor: "pointer" }}>
            <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
            Dry run (simulate without making changes)
          </label>
        )}

        {runbook.risk_level.toLowerCase() === "high" && !dryRun && (
          <div className="error-banner" style={{ marginBottom: "1rem" }}>
            ⚠ High-risk runbook. Review the steps carefully before executing.
          </div>
        )}

        {err && <div className="error-banner" style={{ marginBottom: ".75rem" }}>{err}</div>}

        <div style={{ display: "flex", gap: ".75rem" }}>
          <button className="btn btn-primary" onClick={handleRun} disabled={running || (needsVm && !params[vmParamKey])}>
            {running ? "Running…" : dryRun ? "Run Dry Run" : "Execute"}
          </button>
          <button className="btn btn-secondary" onClick={onClose} disabled={running}>Cancel</button>
        </div>
      </aside>
    </>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

export function Runbooks() {
  const [runbooks, setRunbooks] = useState<Runbook[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Runbook | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState("");
  const [tab, setTab] = useState<"catalog" | "history">("catalog");
  // Execution state
  const [execDialog, setExecDialog] = useState<Runbook | null>(null);
  const [execResult, setExecResult] = useState<RunbookExecution | null>(null);
  const [vms, setVms] = useState<Vm[]>([]);
  // History
  const [executions, setExecutions] = useState<RunbookExecution[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  useEffect(() => {
    let active = true;
    apiRunbooks()
      .then((r) => { if (active) setRunbooks(r); })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : "Failed to load"); })
      .finally(() => { if (active) setLoading(false); });
    // Load VMs for target-VM parameter in execute dialog
    apiVms().then((v) => setVms(v)).catch(() => {});
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (tab !== "history") return;
    setHistoryLoading(true);
    apiRunbookExecutions()
      .then(setExecutions)
      .catch(() => {})
      .finally(() => setHistoryLoading(false));
  }, [tab]);

  const openDetail = async (rb: Runbook) => {
    setDetailLoading(true);
    try {
      setSelected(await apiRunbook(rb.name));
    } catch {
      setSelected(rb);          // fall back to list data
    } finally {
      setDetailLoading(false);
    }
  };

  if (loading) return <div className="empty-state"><span className="loading-spinner" /></div>;
  if (error)   return <div className="error-banner">{error}</div>;

  const categories = [...new Set(runbooks.map((r) => r.category))].sort();
  const filtered   = categoryFilter ? runbooks.filter((r) => r.category === categoryFilter) : runbooks;

  return (
    <div>
      {/* Tabs: Catalog | My Executions */}
      <div className="tabs" style={{ marginBottom: "1rem" }}>
        <button className={`tab-btn${tab === "catalog" ? " active" : ""}`} onClick={() => setTab("catalog")}>
          Catalog ({runbooks.length})
        </button>
        <button className={`tab-btn${tab === "history" ? " active" : ""}`} onClick={() => setTab("history")}>
          My Executions
        </button>
      </div>

      {/* ── History tab ── */}
      {tab === "history" && (
        <div>
          {historyLoading && <div className="empty-state"><span className="loading-spinner" /></div>}
          {!historyLoading && executions.length === 0 && (
            <div className="empty-state">No executions yet. Run a runbook from the Catalog tab.</div>
          )}
          {!historyLoading && executions.length > 0 && (
            <div className="card table-wrap" style={{ padding: 0 }}>
              <table>
                <thead>
                  <tr>
                    <th>Runbook</th>
                    <th>Status</th>
                    <th>Mode</th>
                    <th>Risk</th>
                    <th>Triggered</th>
                    <th>Completed</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {executions.map((ex) => (
                    <tr key={ex.execution_id} style={{ cursor: "pointer" }} onClick={() => setExecResult(ex)}>
                      <td style={{ fontWeight: 500 }}>{ex.display_name || ex.runbook_name}</td>
                      <td>{statusBadge(ex.status)}</td>
                      <td>{ex.dry_run ? <span className="badge badge-amber">Dry run</span> : <span className="badge badge-grey">Live</span>}</td>
                      <td><RiskBadge level={ex.risk_level} /></td>
                      <td style={{ fontSize: ".8rem", whiteSpace: "nowrap" }}>{ex.triggered_at ? new Date(ex.triggered_at).toLocaleString() : "—"}</td>
                      <td style={{ fontSize: ".8rem", whiteSpace: "nowrap" }}>{ex.completed_at ? new Date(ex.completed_at).toLocaleString() : "—"}</td>
                      <td>
                        <button className="btn btn-ghost btn-sm" onClick={(e) => { e.stopPropagation(); setExecResult(ex); }}>
                          View
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── Catalog tab ── */}
      {tab === "catalog" && (
        <>
          <div className="filter-bar">
            <select className="select" value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
              <option value="">All categories</option>
              {categories.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <span style={{ fontSize: ".8rem", color: "var(--color-text-secondary)" }}>
              {filtered.length} runbook{filtered.length !== 1 ? "s" : ""}
            </span>
          </div>

          {filtered.length === 0 ? (
            <div className="empty-state">No runbooks available for your environment yet.</div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "1rem" }}>
              {filtered.map((rb) => (
                <div
                  key={rb.name}
                  className="card"
                  style={{ display: "flex", flexDirection: "column", gap: ".5rem" }}
                >
                  <div style={{ display: "flex", alignItems: "flex-start", gap: ".5rem", cursor: "pointer" }}
                    onClick={() => openDetail(rb)} role="button" tabIndex={0}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") openDetail(rb); }}>
                    <span style={{ fontSize: "1.15rem" }} aria-hidden="true">{categoryIcon(rb.category)}</span>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 600, fontSize: ".9rem", marginBottom: ".15rem" }}>{rb.display_name}</div>
                      <div style={{ fontSize: ".75rem", color: "var(--color-text-secondary)" }}>{rb.category}</div>
                    </div>
                    <RiskBadge level={rb.risk_level} />
                  </div>
                  <div style={{ fontSize: ".8125rem", color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                    {rb.description}
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "auto" }}>
                    <div style={{ fontSize: ".7rem", color: "var(--color-text-secondary)" }}>
                      Updated: {new Date(rb.updated_at).toLocaleDateString()}
                    </div>
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={() => { setExecDialog(rb); setSelected(null); }}
                    >
                      ▶ Execute
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* ── Execute dialog ── */}
      {execDialog && (
        <ExecuteDialog
          runbook={execDialog}
          vms={vms}
          onClose={() => setExecDialog(null)}
          onDone={(ex) => {
            setExecDialog(null);
            setExecResult(ex);
            if (tab === "history") {
              apiRunbookExecutions().then(setExecutions).catch(() => {});
            }
          }}
        />
      )}

      {/* ── Execution result panel ── */}
      {execResult && (
        <ExecutionResultPanel exec={execResult} onClose={() => setExecResult(null)} />
      )}

      {/* ── Detail side panel ── */}
      {(selected !== null || detailLoading) && (
        <>
          <div className="side-panel-overlay" onClick={() => { if (!detailLoading) setSelected(null); }} />
          <aside className="side-panel" aria-label="Runbook detail">
            {detailLoading ? (
              <div className="empty-state"><span className="loading-spinner" /></div>
            ) : selected && (
              <>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: ".75rem", marginBottom: "1.25rem" }}>
                  <div style={{ flex: 1 }}>
                    <h2 style={{ fontSize: "1.125rem", fontWeight: 700 }}>{selected.display_name}</h2>
                    <div style={{ display: "flex", gap: ".5rem", marginTop: ".4rem", flexWrap: "wrap" }}>
                      <span className="badge badge-blue">{selected.category}</span>
                      <RiskBadge level={selected.risk_level} />
                    </div>
                  </div>
                  <button
                    className="btn btn-secondary"
                    onClick={() => setSelected(null)}
                    aria-label="Close"
                    style={{ padding: ".35rem .65rem", flexShrink: 0 }}
                  >
                    ✕
                  </button>
                </div>

                <p style={{ fontSize: ".875rem", color: "var(--color-text-secondary)", marginBottom: "1.25rem", lineHeight: 1.6 }}>
                  {selected.description}
                </p>

                {selected.prerequisites && (
                  <div style={{ marginBottom: "1.25rem" }}>
                    <div className="section-title">Prerequisites</div>
                    <p style={{ fontSize: ".875rem", lineHeight: 1.6 }}>{selected.prerequisites}</p>
                  </div>
                )}

                <div style={{ marginBottom: "1.25rem" }}>
                  <div className="section-title">Steps</div>
                  <ol style={{ paddingLeft: "1.25rem", display: "flex", flexDirection: "column", gap: ".6rem" }}>
                    {selected.steps.map((step, i) => (
                      <li key={i} style={{ fontSize: ".875rem", lineHeight: 1.6 }}>{step}</li>
                    ))}
                  </ol>
                </div>

                {selected.expected_outcome && (
                  <div style={{ background: "var(--color-surface-elevated)", borderRadius: "var(--radius-sm)", padding: ".75rem", marginBottom: "1rem" }}>
                    <div style={{ fontSize: ".8125rem", fontWeight: 600, marginBottom: ".25rem" }}>Expected outcome</div>
                    <p style={{ fontSize: ".875rem", color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                      {selected.expected_outcome}
                    </p>
                  </div>
                )}

                <button
                  className="btn btn-primary"
                  style={{ width: "100%" }}
                  onClick={() => { setExecDialog(selected); setSelected(null); }}
                >
                  ▶ Execute this runbook
                </button>
              </>
            )}
          </aside>
        </>
      )}
    </div>
  );
}
