import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  apiVms,
  apiRestorePoints,
  apiRestorePlan,
  apiRestoreExecute,
  apiRestoreJob,
  apiRestoreJobs,
  apiRestoreCancel,
  apiRestoreAvailableIps,
  apiRestoreSendEmail,
  apiSecurityGroups,
  apiSyncAndSnapshot,
  apiNetworks,
  type Vm,
  type RestorePoint,
  type RestoreJob,
  type SecurityGroup,
  type Network,
  type AvailableIpsResponse,
} from "../lib/api";

// ── Job status badge ─────────────────────────────────────────────────────────

function JobStatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase();
  if (s === "completed" || s === "succeeded" || s === "success") return <span className="badge badge-green">Completed</span>;
  if (s === "failed"    || s === "error")   return <span className="badge badge-red">Failed</span>;
  if (s === "running"   || s === "in_progress") return <span className="badge badge-blue">Running</span>;
  if (s === "pending")  return <span className="badge badge-amber">Pending</span>;
  if (s === "canceled" || s === "cancelled") return <span className="badge badge-grey">Cancelled</span>;
  return <span className="badge badge-grey">{status}</span>;
}

const ACTIVE_STATUSES   = new Set(["pending", "running", "in_progress"]);
const TERMINAL_STATUSES = new Set(["succeeded", "completed", "success", "failed", "error", "canceled", "cancelled", "interrupted"]);

// ── Result panel shown after job completes ───────────────────────────────────

function RestoreResultPanel({
  job,
  onClose,
  onSendEmail,
}: {
  job: RestoreJob;
  onClose: () => void;
  onSendEmail: (email: string) => Promise<void>;
}) {
  const [emailInput, setEmailInput] = useState("");
  const [emailSending, setEmailSending] = useState(false);
  const [emailSent, setEmailSent] = useState(false);
  const [emailError, setEmailError] = useState<string | null>(null);

  const succeeded = ["succeeded", "completed", "success"].includes(job.status.toLowerCase());
  const duration = (() => {
    if (!job.created_at || !job.updated_at) return null;
    const secs = Math.round(
      (new Date(job.updated_at).getTime() - new Date(job.created_at).getTime()) / 1000
    );
    if (secs < 0) return null;
    return secs < 60 ? `${secs}s` : `${Math.floor(secs / 60)}m ${secs % 60}s`;
  })();

  const handleSendEmail = async () => {
    if (!emailInput.trim()) return;
    setEmailSending(true);
    setEmailError(null);
    try {
      await onSendEmail(emailInput.trim());
      setEmailSent(true);
    } catch (e: unknown) {
      setEmailError(e instanceof Error ? e.message : "Failed to send email");
    } finally {
      setEmailSending(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.45)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center", padding: "1rem" }}>
      <div className="card" style={{ width: "100%", maxWidth: 520, padding: "1.75rem", position: "relative" }}>
        <button onClick={onClose} style={{ position: "absolute", top: ".75rem", right: ".75rem", background: "none", border: "none", cursor: "pointer", fontSize: "1.2rem", color: "var(--color-text-secondary)" }} aria-label="Close">×</button>

        {succeeded ? (
          <>
            <div style={{ fontSize: "2.5rem", textAlign: "center", marginBottom: ".5rem" }}>✅</div>
            <div style={{ textAlign: "center", fontWeight: 700, fontSize: "1.1rem", marginBottom: "1.25rem", color: "var(--color-success)" }}>Restore Completed Successfully</div>
            <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: ".4rem .75rem", marginBottom: "1.25rem", fontSize: ".875rem" }}>
              {([
                ["Source VM",   job.vm_name],
                ["New VM name", job.new_vm_name || "—"],
                ["IP(s)",       job.result?.new_ips?.length ? job.result.new_ips.join(", ") : "—"],
                ["Mode",        job.mode === "REPLACE" ? "Replace in-place" : "New copy"],
                ["Duration",    duration ?? "—"],
                ["Snapshot",    job.restore_point_name || "—"],
              ] as [string, string][]).map(([k, v]) => (
                <React.Fragment key={k}>
                  <dt style={{ fontWeight: 600, color: "var(--color-text-secondary)", whiteSpace: "nowrap" }}>{k}</dt>
                  <dd style={{ margin: 0 }}>{v}</dd>
                </React.Fragment>
              ))}
            </dl>
          </>
        ) : (
          <>
            <div style={{ fontSize: "2.5rem", textAlign: "center", marginBottom: ".5rem" }}>❌</div>
            <div style={{ textAlign: "center", fontWeight: 700, fontSize: "1.1rem", marginBottom: "1.25rem", color: "var(--color-error)" }}>
              Restore {job.status.charAt(0).toUpperCase() + job.status.slice(1).toLowerCase()}
            </div>
            <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: ".4rem .75rem", marginBottom: "1.25rem", fontSize: ".875rem" }}>
              {([
                ["Source VM", job.vm_name],
                ["Status",    job.status],
                ["Duration",  duration ?? "—"],
              ] as [string, string][]).map(([k, v]) => (
                <React.Fragment key={k}>
                  <dt style={{ fontWeight: 600, color: "var(--color-text-secondary)", whiteSpace: "nowrap" }}>{k}</dt>
                  <dd style={{ margin: 0 }}>{v}</dd>
                </React.Fragment>
              ))}
            </dl>
            {(job.failure_reason || job.error_message) && (
              <div style={{ background: "rgba(255,80,80,.07)", border: "1px solid var(--color-error)", borderRadius: "6px", padding: ".75rem 1rem", marginBottom: "1.25rem", fontSize: ".875rem" }}>
                <div style={{ fontWeight: 600, marginBottom: ".3rem", color: "var(--color-error)" }}>Failure reason</div>
                <div style={{ wordBreak: "break-word" }}>{job.failure_reason || job.error_message}</div>
              </div>
            )}
          </>
        )}

        <div style={{ borderTop: "1px solid var(--color-border)", paddingTop: "1rem" }}>
          <div style={{ fontSize: ".8125rem", fontWeight: 600, marginBottom: ".5rem" }}>Send summary by email</div>
          {emailSent ? (
            <div className="success-banner" style={{ marginBottom: 0 }}>Summary sent ✓</div>
          ) : (
            <div style={{ display: "flex", gap: ".5rem" }}>
              <input type="email" className="input" style={{ flex: 1, fontSize: ".875rem" }} placeholder="your@email.com" value={emailInput} onChange={(e) => setEmailInput(e.target.value)} disabled={emailSending} />
              <button className="btn btn-secondary" style={{ flexShrink: 0 }} disabled={emailSending || !emailInput.trim()} onClick={handleSendEmail}>
                {emailSending ? <span className="loading-spinner" /> : "Send"}
              </button>
            </div>
          )}
          {emailError && <div className="error-banner" style={{ marginTop: ".5rem", marginBottom: 0 }}>{emailError}</div>}
        </div>
      </div>
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

export function RestoreCenter() {
  const [vms, setVms] = useState<Vm[]>([]);
  const [jobs, setJobs] = useState<RestoreJob[]>([]);
  const [securityGroups, setSecurityGroups] = useState<SecurityGroup[]>([]);
  const [networks, setNetworks] = useState<Network[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [syncLoading, setSyncLoading] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);

  // Wizard state
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [selectedVm, setSelectedVm] = useState<Vm | null>(null);
  const [restorePoints, setRestorePoints] = useState<RestorePoint[]>([]);
  const [rpLoading, setRpLoading] = useState(false);
  const [selectedPoint, setSelectedPoint] = useState<RestorePoint | null>(null);
  const [mode, setMode] = useState<"NEW" | "REPLACE">("NEW");
  const [safetySnapshot, setSafetySnapshot] = useState(true);
  const [newVmName, setNewVmName] = useState("");
  const [confirmVmName, setConfirmVmName] = useState("");
  const [ipStrategy, setIpStrategy] = useState<"NEW_IPS" | "TRY_SAME_IPS" | "MANUAL_IP">("NEW_IPS");
  const [selectedSgIds, setSelectedSgIds] = useState<string[]>([]);
  const [cleanupOldStorage, setCleanupOldStorage] = useState(false);
  const [deleteSourceSnapshot, setDeleteSourceSnapshot] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [cancellingId, setCancellingId] = useState<string | null>(null);

  // Manual IP / network selection
  const [selectedNetworkId, setSelectedNetworkId] = useState<string>("");
  const [manualIp, setManualIp] = useState<string>("");
  const [availableIps, setAvailableIps] = useState<AvailableIpsResponse | null>(null);
  const [loadingAvailIps, setLoadingAvailIps] = useState(false);

  // Post-restore result
  const [completedJob, setCompletedJob] = useState<RestoreJob | null>(null);
  const pollingRef = useRef<number | null>(null);

  // Expanded completed job detail
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);

  const refresh = useCallback(() => {
    Promise.all([apiVms(), apiRestoreJobs(), apiSecurityGroups(), apiNetworks()])
      .then(([v, j, sg, nets]) => { setVms(v); setJobs(j); setSecurityGroups(sg); setNetworks(nets); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // Fetch available IPs when a network is selected for MANUAL_IP
  useEffect(() => {
    if (ipStrategy !== "MANUAL_IP" || !selectedNetworkId) {
      setAvailableIps(null);
      return;
    }
    let cancelled = false;
    setLoadingAvailIps(true);
    apiRestoreAvailableIps(selectedNetworkId)
      .then((res) => { if (!cancelled) setAvailableIps(res); })
      .catch(() => { if (!cancelled) setAvailableIps(null); })
      .finally(() => { if (!cancelled) setLoadingAvailIps(false); });
    return () => { cancelled = true; };
  }, [ipStrategy, selectedNetworkId]);

  // Poll for job completion after execution
  const startPolling = useCallback((jobId: string) => {
    if (pollingRef.current) clearInterval(pollingRef.current);
    const poll = async () => {
      try {
        const j = await apiRestoreJob(jobId);
        setJobs((prev) => prev.map((p) => (p.job_id === jobId ? j : p)));
        if (TERMINAL_STATUSES.has(j.status.toLowerCase())) {
          if (pollingRef.current) clearInterval(pollingRef.current);
          setCompletedJob(j);
        }
      } catch { /* continue */ }
    };
    poll();
    pollingRef.current = window.setInterval(poll, 3000);
  }, []);

  useEffect(() => { return () => { if (pollingRef.current) clearInterval(pollingRef.current); }; }, []);

  const handleSyncAndSnapshot = async () => {
    setSyncLoading(true);
    setSyncMsg(null);
    try {
      const res = await apiSyncAndSnapshot();
      setSyncMsg(res.message);
      setTimeout(() => setSyncMsg(null), 8000);
      refresh();
    } catch (e: unknown) {
      setSyncMsg(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setSyncLoading(false);
    }
  };

  const selectVm = async (vm: Vm) => {
    setSelectedVm(vm);
    setStep(2);
    setRpLoading(true);
    setRestorePoints([]);
    setSelectedPoint(null);
    setMode("NEW");
    setSafetySnapshot(true);
    setConfirmVmName("");
    setIpStrategy("NEW_IPS");
    setSelectedSgIds([]);
    setCleanupOldStorage(false);
    setDeleteSourceSnapshot(false);
    setSubmitError(null);
    setSelectedNetworkId("");
    setManualIp("");
    setAvailableIps(null);
    try {
      setRestorePoints(await apiRestorePoints(vm.vm_id));
    } finally {
      setRpLoading(false);
    }
  };

  const selectPoint = (pt: RestorePoint) => {
    setSelectedPoint(pt);
    setNewVmName(`${selectedVm?.vm_name ?? "vm"}-restored-${new Date().toISOString().slice(0, 10)}`);
    if (mode === "REPLACE") setIpStrategy("TRY_SAME_IPS");
    setStep(3);
    setConfirmVmName("");
    setSubmitError(null);
  };

  const handleExecute = async () => {
    if (!selectedVm || !selectedPoint) return;
    if (mode === "REPLACE" && confirmVmName !== selectedVm.vm_name) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const body: Parameters<typeof apiRestorePlan>[0] = {
        vm_id:                selectedVm.vm_id,
        snapshot_id:          selectedPoint.snapshot_id,
        region_id:            selectedVm.region_id,
        new_vm_name:          mode === "NEW" ? (newVmName.trim() || undefined) : undefined,
        mode,
        pre_restore_snapshot: safetySnapshot,
        ip_strategy:          ipStrategy,
        security_group_ids:   selectedSgIds.length > 0 ? selectedSgIds : undefined,
        cleanup_old_storage:  mode === "REPLACE" ? cleanupOldStorage : false,
        delete_source_snapshot: deleteSourceSnapshot,
      };
      if (ipStrategy === "MANUAL_IP") {
        if (selectedNetworkId && manualIp.trim()) body.manual_ips = { [selectedNetworkId]: manualIp.trim() };
        if (selectedNetworkId) body.network_override_id = selectedNetworkId;
      }
      const plan = await apiRestorePlan(body);
      const result = await apiRestoreExecute(plan.plan_id);
      setStep(1);
      setSelectedVm(null);
      setSelectedPoint(null);
      setConfirmVmName("");
      refresh();
      if (result.job_id) startPolling(result.job_id);
    } catch (e: unknown) {
      setSubmitError(e instanceof Error ? e.message : "Restore failed. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = async (jobId: string) => {
    setCancellingId(jobId);
    try {
      await apiRestoreCancel(jobId);
      refresh();
    } finally {
      setCancellingId(null);
    }
  };

  const resetWizard = () => {
    setStep(1);
    setSelectedVm(null);
    setSelectedPoint(null);
    setMode("NEW");
    setSafetySnapshot(true);
    setConfirmVmName("");
    setIpStrategy("NEW_IPS");
    setSelectedSgIds([]);
    setCleanupOldStorage(false);
    setDeleteSourceSnapshot(false);
    setSubmitError(null);
    setSelectedNetworkId("");
    setManualIp("");
    setAvailableIps(null);
  };

  if (loading) return <div className="empty-state"><span className="loading-spinner" /></div>;
  if (error)   return <div className="error-banner">{error}</div>;

  const sortedVms = [...vms].sort((a, b) => {
    if (!a.last_snapshot_ts && !b.last_snapshot_ts) return 0;
    if (!a.last_snapshot_ts) return 1;
    if (!b.last_snapshot_ts) return -1;
    return new Date(b.last_snapshot_ts).getTime() - new Date(a.last_snapshot_ts).getTime();
  });

  const activeJobs    = jobs.filter((j) => ACTIVE_STATUSES.has(j.status.toLowerCase()));
  const completedJobs = jobs.filter((j) => !ACTIVE_STATUSES.has(j.status.toLowerCase()));
  const allAvailableIps = availableIps?.subnets.flatMap((s) => s.available_ips) ?? [];

  return (
    <>
      {completedJob && (
        <RestoreResultPanel
          job={completedJob}
          onClose={() => setCompletedJob(null)}
          onSendEmail={async (email) => { await apiRestoreSendEmail(completedJob.job_id, email); }}
        />
      )}

      <div className="wizard-layout">
        {/* ── Left: Wizard ── */}
        <div>
          <div className="step-indicator">
            {([1, 2, 3] as const).map((s) => (
              <React.Fragment key={s}>
                <div className={`step-dot${step === s ? " active" : step > s ? " done" : ""}`}>{step > s ? "✓" : s}</div>
                {s < 3 && <div className="step-line" />}
              </React.Fragment>
            ))}
          </div>

          {/* Step 1 — Select VM */}
          {step === 1 && (
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
                <div className="section-title" style={{ marginBottom: 0 }}>Step 1 — Select a VM to restore</div>
                <button className="btn btn-secondary" disabled={syncLoading} onClick={handleSyncAndSnapshot} title="Sync inventory and take a snapshot of all VMs now">
                  {syncLoading ? <span className="loading-spinner" /> : "⟳ Sync & Snapshot Now"}
                </button>
              </div>
              {syncMsg && <div className="info-banner" style={{ marginBottom: "1rem" }}>{syncMsg}</div>}
              {sortedVms.length === 0 ? (
                <div className="empty-state">No VMs available.</div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: ".5rem" }}>
                  {sortedVms.map((vm) => (
                    <button key={vm.vm_id} className="card" style={{ textAlign: "left", cursor: "pointer", padding: ".875rem 1rem", border: "1px solid var(--color-border)", background: "var(--color-surface)", width: "100%" }} onClick={() => selectVm(vm)}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: ".5rem" }}>
                        <div>
                          <div style={{ fontWeight: 600, marginBottom: ".2rem" }}>{vm.vm_name}</div>
                          <div style={{ fontSize: ".8125rem", color: "var(--color-text-secondary)" }}>{vm.region_display_name} · {vm.vcpus} vCPU · {(vm.ram_mb / 1024).toFixed(0)} GB RAM</div>
                        </div>
                        <div style={{ textAlign: "right", flexShrink: 0 }}>
                          {vm.compliance_pct !== null && <div style={{ fontSize: ".75rem", color: vm.compliance_pct >= 90 ? "var(--color-success)" : "var(--color-warning)" }}>{vm.compliance_pct.toFixed(0)}% covered</div>}
                          {vm.last_snapshot_ts && <div style={{ fontSize: ".75rem", color: "var(--color-text-secondary)" }}>Last: {new Date(vm.last_snapshot_ts).toLocaleDateString()}</div>}
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Step 2 — Select restore mode + restore point */}
          {step === 2 && selectedVm && (
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: ".75rem", marginBottom: "1rem" }}>
                <button className="btn btn-secondary" onClick={resetWizard} style={{ padding: ".35rem .65rem" }}>← Back</button>
                <div className="section-title" style={{ marginBottom: 0 }}>Step 2 — Restore <strong>{selectedVm.vm_name}</strong></div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: ".75rem", marginBottom: "1.25rem" }}>
                <button className="card" style={{ textAlign: "left", cursor: "pointer", padding: ".875rem 1rem", border: `2px solid ${mode === "NEW" ? "var(--brand-primary)" : "var(--color-border)"}`, background: mode === "NEW" ? "var(--color-surface-active, var(--color-surface))" : "var(--color-surface)", width: "100%" }} onClick={() => setMode("NEW")}>
                  <div style={{ fontWeight: 600, marginBottom: ".3rem" }}>{mode === "NEW" ? "✓ " : ""}Restore to New VM</div>
                  <div style={{ fontSize: ".8rem", color: "var(--color-text-secondary)" }}>Creates a copy alongside the existing VM. Non-destructive.</div>
                </button>
                <button className="card" style={{ textAlign: "left", cursor: "pointer", padding: ".875rem 1rem", border: `2px solid ${mode === "REPLACE" ? "var(--color-error)" : "var(--color-border)"}`, background: mode === "REPLACE" ? "var(--color-surface-active, var(--color-surface))" : "var(--color-surface)", width: "100%" }} onClick={() => setMode("REPLACE")}>
                  <div style={{ fontWeight: 600, marginBottom: ".3rem", color: mode === "REPLACE" ? "var(--color-error)" : undefined }}>{mode === "REPLACE" ? "✓ " : ""}Replace VM In-Place</div>
                  <div style={{ fontSize: ".8rem", color: "var(--color-text-secondary)" }}>Deletes the existing VM and recreates it from the snapshot. Destructive.</div>
                </button>
              </div>
              {mode === "NEW" && <div className="info-banner" style={{ marginBottom: "1rem" }}>A NEW copy of this VM will be created alongside the existing one. Your running VM is unaffected.</div>}
              {mode === "REPLACE" && <div className="error-banner" style={{ marginBottom: "1rem", background: "rgba(255,100,100,.08)" }}>⚠ <strong>Destructive operation:</strong> The existing VM will be deleted before a new one is created from the snapshot. A safety snapshot is automatically taken first.</div>}
              {rpLoading && <div className="empty-state"><span className="loading-spinner" /></div>}
              {!rpLoading && restorePoints.length === 0 && <div className="empty-state">No restore points available for this VM.</div>}
              {!rpLoading && restorePoints.map((pt) => (
                <button key={pt.snapshot_id} className="card" style={{ width: "100%", textAlign: "left", cursor: "pointer", padding: ".75rem 1rem", marginBottom: ".5rem", border: "1px solid var(--color-border)", background: "var(--color-surface)" }} onClick={() => selectPoint(pt)}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div>
                      <div style={{ fontWeight: 500, marginBottom: ".15rem" }}>{pt.snapshot_name}</div>
                      <div style={{ fontSize: ".8125rem", color: "var(--color-text-secondary)" }}>{new Date(pt.created_at).toLocaleString()}{pt.size_gb !== null && ` · ${pt.size_gb.toFixed(1)} GB`}</div>
                    </div>
                    <span className={`badge ${pt.status.toLowerCase() === "available" ? "badge-green" : "badge-amber"}`}>{pt.status}</span>
                  </div>
                </button>
              ))}
            </div>
          )}

          {/* Step 3 — Review & Confirm */}
          {step === 3 && selectedVm && selectedPoint && (
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: ".75rem", marginBottom: "1rem" }}>
                <button className="btn btn-secondary" onClick={() => setStep(2)} style={{ padding: ".35rem .65rem" }}>← Back</button>
                <div className="section-title" style={{ marginBottom: 0 }}>Step 3 — Review & Confirm</div>
              </div>

              <div className="card" style={{ marginBottom: "1rem" }}>
                <dl style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: ".75rem 1rem" }}>
                  {([
                    ["VM",            selectedVm.vm_name],
                    ["Region",        selectedVm.region_display_name],
                    ["Mode",          mode === "REPLACE" ? "⚠ Replace In-Place" : "New VM (safe copy)"],
                    ["Snapshot",      selectedPoint.snapshot_name],
                    ["Snapshot date", new Date(selectedPoint.created_at).toLocaleString()],
                  ] as [string, string][]).map(([k, v]) => (
                    <div key={k}>
                      <dt style={{ fontSize: ".7rem", fontWeight: 600, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: ".04em" }}>{k}</dt>
                      <dd style={{ fontSize: ".875rem", color: k === "Mode" && mode === "REPLACE" ? "var(--color-error)" : undefined }}>{v}</dd>
                    </div>
                  ))}
                </dl>
              </div>

              {mode === "NEW" && (
                <>
                  <div className="field">
                    <label htmlFor="new-vm-name">Name for restored VM</label>
                    <input id="new-vm-name" className="input" type="text" value={newVmName} onChange={(e) => setNewVmName(e.target.value)} disabled={submitting} placeholder="my-vm-restored-2026-04-14" />
                  </div>
                  <label style={{ display: "flex", alignItems: "flex-start", gap: ".5rem", marginBottom: "1rem", cursor: submitting ? "default" : "pointer", fontWeight: 400 }}>
                    <input type="checkbox" checked={safetySnapshot} onChange={(e) => setSafetySnapshot(e.target.checked)} disabled={submitting} style={{ marginTop: ".15rem" }} />
                    <span>
                      <strong>Take a snapshot before restore</strong>
                      <span style={{ display: "block", fontSize: ".8rem", color: "var(--color-text-secondary)" }}>Recommended. Captures the current VM state as a restore point before creating the new copy.</span>
                    </span>
                  </label>
                </>
              )}

              {mode === "REPLACE" && (
                <>
                  <div style={{ background: "rgba(255,80,80,.07)", border: "1px solid var(--color-error)", borderRadius: "6px", padding: ".875rem 1rem", marginBottom: "1rem" }}>
                    <div style={{ fontWeight: 600, color: "var(--color-error)", marginBottom: ".4rem" }}>⚠ Destructive operation — please read carefully</div>
                    <ul style={{ margin: 0, paddingLeft: "1.2rem", fontSize: ".875rem", lineHeight: 1.6 }}>
                      <li>A <strong>safety snapshot</strong> will be taken of the current VM before it is deleted.</li>
                      <li>The existing VM <strong>{selectedVm.vm_name}</strong> will be <strong>permanently deleted</strong>.</li>
                      <li>A new VM will be created from the selected snapshot with the same name.</li>
                    </ul>
                  </div>
                  <label style={{ display: "flex", alignItems: "flex-start", gap: ".5rem", marginBottom: "1rem", cursor: "pointer", fontWeight: 400 }}>
                    <input type="checkbox" checked={safetySnapshot} onChange={() => {}} disabled={true} style={{ marginTop: ".15rem" }} />
                    <span>
                      <strong>Take a safety snapshot before deleting</strong>
                      <span style={{ display: "block", fontSize: ".8rem", color: "var(--color-text-secondary)" }}>Mandatory for self-service replace operations.</span>
                    </span>
                  </label>
                  <div className="field">
                    <label htmlFor="confirm-vm-name">Type <strong>DELETE AND RESTORE {selectedVm.vm_name}</strong> to confirm</label>
                    <input id="confirm-vm-name" className="input" type="text" value={confirmVmName} onChange={(e) => setConfirmVmName(e.target.value)} disabled={submitting} placeholder={`DELETE AND RESTORE ${selectedVm.vm_name}`} autoComplete="off" />
                  </div>
                </>
              )}

              {/* Network / IP strategy */}
              {mode === "REPLACE" ? (
                <div style={{ marginBottom: "1rem", padding: ".6rem .875rem", background: "var(--color-surface-elevated, var(--color-surface))", border: "1px solid var(--color-border)", borderRadius: "6px", fontSize: ".875rem" }}>
                  <span style={{ fontWeight: 600 }}>IP Strategy: </span>
                  <span style={{ color: "var(--color-text-secondary)" }}>Original IPs will be preserved where possible. Cannot be changed for in-place replace.</span>
                </div>
              ) : (
                <>
                  <div className="field" style={{ marginBottom: "1rem" }}>
                    <label htmlFor="ip-strategy">IP Strategy</label>
                    <select id="ip-strategy" className="select" value={ipStrategy} onChange={(e) => { setIpStrategy(e.target.value as "NEW_IPS" | "TRY_SAME_IPS" | "MANUAL_IP"); setSelectedNetworkId(""); setManualIp(""); setAvailableIps(null); }} disabled={submitting}>
                      <option value="NEW_IPS">Allocate new IPs (safest)</option>
                      <option value="TRY_SAME_IPS">Try to keep original IPs (best-effort)</option>
                      <option value="MANUAL_IP">Select network &amp; IP manually</option>
                    </select>
                  </div>

                  {ipStrategy === "MANUAL_IP" && (
                    <div style={{ background: "var(--color-surface-elevated, var(--color-surface))", border: "1px solid var(--color-border)", borderRadius: "6px", padding: ".875rem 1rem", marginBottom: "1rem" }}>
                      <div style={{ fontWeight: 600, fontSize: ".85rem", marginBottom: ".75rem" }}>
                        Network &amp; IP Selection
                        <span style={{ fontWeight: 400, color: "var(--color-text-secondary)", marginLeft: ".4rem" }}>— choose any network (can differ from the source VM's network)</span>
                      </div>
                      <div className="field" style={{ marginBottom: ".75rem" }}>
                        <label htmlFor="network-select" style={{ fontSize: ".82rem" }}>Target network</label>
                        <select id="network-select" className="select" value={selectedNetworkId} onChange={(e) => { setSelectedNetworkId(e.target.value); setManualIp(""); setAvailableIps(null); }} disabled={submitting}>
                          <option value="">— Select a network —</option>
                          {networks
                            .filter((n) => !selectedVm.region_id || n.region_id === selectedVm.region_id)
                            .map((n) => (
                              <option key={n.id} value={n.id}>
                                {n.name || n.id}{n.subnets.some((s) => s.enable_dhcp === false) ? " (no DHCP)" : ""}
                              </option>
                            ))}
                        </select>
                      </div>

                      {selectedNetworkId && (
                        <div className="field" style={{ marginBottom: 0 }}>
                          <label htmlFor="manual-ip" style={{ fontSize: ".82rem" }}>IP address</label>
                          {loadingAvailIps ? (
                            <div style={{ padding: ".5rem 0", fontSize: ".82rem", color: "var(--color-text-secondary)" }}>Loading available IPs…</div>
                          ) : allAvailableIps.length > 0 ? (
                            <>
                              <select id="manual-ip" className="select" value={manualIp} onChange={(e) => setManualIp(e.target.value)} disabled={submitting}>
                                <option value="">— Select an available IP —</option>
                                {allAvailableIps.map((ip) => <option key={ip} value={ip}>{ip}</option>)}
                              </select>
                              <div style={{ fontSize: ".75rem", color: "var(--color-success)", marginTop: ".2rem" }}>{allAvailableIps.length} available IP{allAvailableIps.length !== 1 ? "s" : ""}</div>
                            </>
                          ) : (
                            <>
                              {availableIps && <div style={{ fontSize: ".78rem", color: "var(--color-warning)", marginBottom: ".35rem" }}>No free IPs returned — enter one manually</div>}
                              <input id="manual-ip" className="input" type="text" value={manualIp} onChange={(e) => setManualIp(e.target.value)} disabled={submitting} placeholder="e.g. 192.168.1.50" />
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}

              {/* Security groups */}
              {securityGroups.length > 0 && (
                <div style={{ marginBottom: "1rem" }}>
                  <div style={{ fontSize: ".8125rem", fontWeight: 600, marginBottom: ".4rem" }}>Security Groups (optional)</div>
                  <div style={{ border: "1px solid var(--color-border)", borderRadius: "6px", padding: ".5rem", maxHeight: "140px", overflowY: "auto" }}>
                    {securityGroups.map((sg) => (
                      <label key={sg.id} style={{ display: "flex", alignItems: "center", gap: ".5rem", padding: ".25rem 0", cursor: "pointer", fontSize: ".875rem" }}>
                        <input type="checkbox" checked={selectedSgIds.includes(sg.id)} onChange={(e) => { setSelectedSgIds(prev => e.target.checked ? [...prev, sg.id] : prev.filter(id => id !== sg.id)); }} disabled={submitting} />
                        <span style={{ fontWeight: 500 }}>{sg.name}</span>
                        {sg.description && <span style={{ color: "var(--color-text-secondary)", fontSize: ".75rem" }}>{sg.description}</span>}
                      </label>
                    ))}
                  </div>
                  <div style={{ fontSize: ".75rem", color: "var(--color-text-secondary)", marginTop: ".2rem" }}>
                    {selectedSgIds.length > 0 ? `${selectedSgIds.length} selected` : "None selected — project default will be used"}
                  </div>
                </div>
              )}

              {/* Storage cleanup */}
              <div style={{ background: "var(--color-surface-elevated, var(--color-surface))", border: "1px solid var(--color-border)", borderRadius: "6px", padding: ".75rem 1rem", marginBottom: "1rem" }}>
                <div style={{ fontSize: ".8125rem", fontWeight: 600, marginBottom: ".5rem" }}>Post-Restore Storage Cleanup (optional)</div>
                {mode === "REPLACE" && (
                  <label style={{ display: "flex", alignItems: "flex-start", gap: ".5rem", marginBottom: ".4rem", cursor: submitting ? "default" : "pointer", fontWeight: 400, fontSize: ".875rem" }}>
                    <input type="checkbox" checked={cleanupOldStorage} onChange={(e) => setCleanupOldStorage(e.target.checked)} disabled={submitting} style={{ marginTop: ".15rem" }} />
                    <span><strong>Delete original VM's volume after restore</strong><span style={{ display: "block", fontSize: ".8rem", color: "var(--color-text-secondary)" }}>The old root volume becomes orphaned. Check this to remove it automatically.</span></span>
                  </label>
                )}
                <label style={{ display: "flex", alignItems: "flex-start", gap: ".5rem", cursor: submitting ? "default" : "pointer", fontWeight: 400, fontSize: ".875rem" }}>
                  <input type="checkbox" checked={deleteSourceSnapshot} onChange={(e) => setDeleteSourceSnapshot(e.target.checked)} disabled={submitting} style={{ marginTop: ".15rem" }} />
                  <span><strong>Delete source snapshot after restore</strong><span style={{ display: "block", fontSize: ".8rem", color: "var(--color-text-secondary)" }}>Remove the Cinder snapshot once the restore completes successfully.</span></span>
                </label>
              </div>

              {submitError && <div className="error-banner" style={{ marginBottom: "1rem" }}>{submitError}</div>}

              <button
                className={`btn ${mode === "REPLACE" ? "btn-danger" : "btn-primary"}`}
                style={{ width: "100%", justifyContent: "center" }}
                disabled={
                  submitting ||
                  (mode === "NEW" && !newVmName.trim()) ||
                  (mode === "REPLACE" && confirmVmName !== `DELETE AND RESTORE ${selectedVm.vm_name}`) ||
                  (ipStrategy === "MANUAL_IP" && (!selectedNetworkId || !manualIp.trim()))
                }
                onClick={handleExecute}
              >
                {submitting ? <span className="loading-spinner" /> : mode === "REPLACE" ? "Replace VM (Destructive)" : "Start Restore"}
              </button>
              {ipStrategy === "MANUAL_IP" && (!selectedNetworkId || !manualIp.trim()) && (
                <div style={{ fontSize: ".78rem", color: "var(--color-text-secondary)", textAlign: "center", marginTop: ".4rem" }}>Select a network and IP address above to continue.</div>
              )}
            </div>
          )}
        </div>

        {/* ── Right: Job panels ── */}
        <div>
          <div className="section-title">Active Jobs</div>
          {activeJobs.length === 0 ? (
            <div className="card empty-state" style={{ padding: "1.25rem", marginBottom: "1.25rem" }}>No active restore jobs.</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: ".75rem", marginBottom: "1.25rem" }}>
              {activeJobs.map((job) => (
                <div key={job.job_id} className="card" style={{ padding: "1rem" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: ".35rem" }}>
                    <div style={{ fontWeight: 600, fontSize: ".875rem" }}>{job.vm_name}</div>
                    <div style={{ display: "flex", gap: ".4rem", alignItems: "center" }}>
                      {job.mode === "REPLACE" && <span className="badge badge-red" style={{ fontSize: ".7rem" }}>Replace</span>}
                      <JobStatusBadge status={job.status} />
                    </div>
                  </div>
                  <div style={{ fontSize: ".8rem", color: "var(--color-text-secondary)", marginBottom: ".5rem" }}>
                    {job.mode === "REPLACE" ? `In-place replace · ${job.region_display_name}` : `→ ${job.new_vm_name} · ${job.region_display_name}`}
                  </div>
                  <div className="progress-track" style={{ marginBottom: ".35rem" }}>
                    <div className="progress-fill" style={{ width: `${job.progress_pct}%` }} />
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: ".75rem" }}>
                    <span style={{ color: "var(--color-text-secondary)" }}>{job.progress_pct}%</span>
                    {job.status.toLowerCase() === "pending" && (
                      <button className="btn btn-danger" style={{ fontSize: ".75rem", padding: ".2rem .5rem" }} disabled={cancellingId === job.job_id} onClick={() => handleCancel(job.job_id)}>Cancel</button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="section-title">Recent Jobs</div>
          {completedJobs.length === 0 ? (
            <div className="card empty-state" style={{ padding: "1.25rem" }}>No completed jobs.</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: ".5rem" }}>
              {completedJobs.slice(0, 10).map((job) => {
                const isExpanded = expandedJobId === job.job_id;
                const succeeded = ["succeeded", "completed", "success"].includes(job.status.toLowerCase());
                return (
                  <div key={job.job_id} className="card" style={{ padding: ".75rem 1rem" }}>
                    <button style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: ".5rem", width: "100%", background: "none", border: "none", cursor: "pointer", textAlign: "left", padding: 0 }} onClick={() => setExpandedJobId(isExpanded ? null : job.job_id)}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 500, fontSize: ".875rem" }}>{job.vm_name}</div>
                        <div style={{ fontSize: ".75rem", color: "var(--color-text-secondary)" }}>
                          {job.mode === "REPLACE" ? "Replace in-place" : `→ ${job.new_vm_name || "new VM"}`}{" · "}{new Date(job.updated_at).toLocaleString()}
                        </div>
                      </div>
                      <div style={{ display: "flex", gap: ".4rem", alignItems: "center", flexShrink: 0 }}>
                        {job.mode === "REPLACE" && <span className="badge badge-red" style={{ fontSize: ".7rem" }}>Replace</span>}
                        <JobStatusBadge status={job.status} />
                        <span style={{ fontSize: ".75rem", color: "var(--color-text-secondary)" }}>{isExpanded ? "▲" : "▼"}</span>
                      </div>
                    </button>

                    {isExpanded && (
                      <div style={{ marginTop: ".75rem", paddingTop: ".75rem", borderTop: "1px solid var(--color-border)", fontSize: ".8125rem" }}>
                        {succeeded ? (
                          <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: ".3rem .75rem", marginBottom: ".6rem" }}>
                            {([
                              ["New VM",   job.new_vm_name || "—"],
                              ["IPs",      job.result?.new_ips?.length ? job.result.new_ips.join(", ") : "—"],
                              ["Snapshot", job.restore_point_name || "—"],
                            ] as [string, string][]).map(([k, v]) => (
                              <React.Fragment key={k}>
                                <dt style={{ fontWeight: 600, color: "var(--color-text-secondary)", whiteSpace: "nowrap" }}>{k}</dt>
                                <dd style={{ margin: 0 }}>{v}</dd>
                              </React.Fragment>
                            ))}
                          </dl>
                        ) : (
                          (job.failure_reason || job.error_message) && (
                            <div style={{ background: "rgba(255,80,80,.07)", border: "1px solid var(--color-error)", borderRadius: "4px", padding: ".5rem .75rem", marginBottom: ".6rem" }}>
                              <div style={{ fontWeight: 600, color: "var(--color-error)", marginBottom: ".2rem", fontSize: ".78rem" }}>Failure reason</div>
                              <div style={{ wordBreak: "break-word" }}>{job.failure_reason || job.error_message}</div>
                            </div>
                          )
                        )}
                        <button className="btn btn-secondary" style={{ fontSize: ".75rem", padding: ".3rem .6rem" }} onClick={() => setCompletedJob(job)}>
                          View full details &amp; email summary
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

