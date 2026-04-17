import React, { useCallback, useEffect, useState } from "react";
import {
  apiVms,
  apiRestorePoints,
  apiRestorePlan,
  apiRestoreExecute,
  apiRestoreJobs,
  apiRestoreCancel,
  apiSecurityGroups,
  apiSyncAndSnapshot,
  type Vm,
  type RestorePoint,
  type RestoreJob,
  type SecurityGroup,
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

const ACTIVE_STATUSES = new Set(["pending", "running", "in_progress"]);

// ── Main component ───────────────────────────────────────────────────────────

export function RestoreCenter() {
  const [vms, setVms] = useState<Vm[]>([]);
  const [jobs, setJobs] = useState<RestoreJob[]>([]);
  const [securityGroups, setSecurityGroups] = useState<SecurityGroup[]>([]);
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
  const [ipStrategy, setIpStrategy] = useState<"NEW_IPS" | "TRY_SAME_IPS">("NEW_IPS");
  const [selectedSgIds, setSelectedSgIds] = useState<string[]>([]);
  const [cleanupOldStorage, setCleanupOldStorage] = useState(false);
  const [deleteSourceSnapshot, setDeleteSourceSnapshot] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [cancellingId, setCancellingId] = useState<string | null>(null);

  const refresh = useCallback(() => {
    Promise.all([apiVms(), apiRestoreJobs(), apiSecurityGroups()])
      .then(([v, j, sg]) => { setVms(v); setJobs(j); setSecurityGroups(sg); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

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

  useEffect(() => { refresh(); }, [refresh]);

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
    try {
      setRestorePoints(await apiRestorePoints(vm.vm_id));
    } finally {
      setRpLoading(false);
    }
  };

  const selectPoint = (pt: RestorePoint) => {
    setSelectedPoint(pt);
    setNewVmName(
      `${selectedVm?.vm_name ?? "vm"}-restored-${new Date().toISOString().slice(0, 10)}`
    );
    // For REPLACE: always preserve original IPs (backend enforces this too)
    if (mode === "REPLACE") setIpStrategy("TRY_SAME_IPS");
    setStep(3);
    setConfirmVmName("");
    setSubmitError(null);
  };

  const handleExecute = async () => {
    if (!selectedVm || !selectedPoint) return;
    // For REPLACE: require typing the VM name exactly
    if (mode === "REPLACE" && confirmVmName !== selectedVm.vm_name) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const plan = await apiRestorePlan({
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
      });
      const job = await apiRestoreExecute(plan.plan_id);
      const modeLabel = mode === "REPLACE" ? "Replace" : "Restore";
      setSuccessMsg(`${modeLabel} started for ${job.vm_name}. Track progress in the jobs panel.`);
      setStep(1);
      setSelectedVm(null);
      setSelectedPoint(null);
      setConfirmVmName("");
      refresh();
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
  };

  if (loading) return <div className="empty-state"><span className="loading-spinner" /></div>;
  if (error)   return <div className="error-banner">{error}</div>;

  // Sort VMs: most recently snapshotted first
  const sortedVms = [...vms].sort((a, b) => {
    if (!a.last_snapshot_ts && !b.last_snapshot_ts) return 0;
    if (!a.last_snapshot_ts) return 1;
    if (!b.last_snapshot_ts) return -1;
    return new Date(b.last_snapshot_ts).getTime() - new Date(a.last_snapshot_ts).getTime();
  });

  const activeJobs    = jobs.filter((j) => ACTIVE_STATUSES.has(j.status.toLowerCase()));
  const completedJobs = jobs.filter((j) => !ACTIVE_STATUSES.has(j.status.toLowerCase()));

  return (
    <div className="wizard-layout">
      {/* ── Left: Wizard ── */}
      <div>
        {/* Step indicator */}
        <div className="step-indicator">
          {([1, 2, 3] as const).map((s) => (
            <React.Fragment key={s}>
              <div className={`step-dot${step === s ? " active" : step > s ? " done" : ""}`}>
                {step > s ? "✓" : s}
              </div>
              {s < 3 && <div className="step-line" />}
            </React.Fragment>
          ))}
        </div>

        {successMsg && (
          <div className="success-banner">{successMsg}</div>
        )}

        {/* Step 1 — Select VM */}
        {step === 1 && (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
              <div className="section-title" style={{ marginBottom: 0 }}>Step 1 — Select a VM to restore</div>
              <button
                className="btn btn-secondary"
                disabled={syncLoading}
                onClick={handleSyncAndSnapshot}
                title="Sync inventory and take a snapshot of all VMs now"
              >
                {syncLoading ? <span className="loading-spinner" /> : "⟳ Sync & Snapshot Now"}
              </button>
            </div>
            {syncMsg && (
              <div className="info-banner" style={{ marginBottom: "1rem" }}>{syncMsg}</div>
            )}
            {sortedVms.length === 0 ? (
              <div className="empty-state">No VMs available.</div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: ".5rem" }}>
                {sortedVms.map((vm) => (
                  <button
                    key={vm.vm_id}
                    className="card"
                    style={{ textAlign: "left", cursor: "pointer", padding: ".875rem 1rem", border: "1px solid var(--color-border)", background: "var(--color-surface)", width: "100%" }}
                    onClick={() => selectVm(vm)}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: ".5rem" }}>
                      <div>
                        <div style={{ fontWeight: 600, marginBottom: ".2rem" }}>{vm.vm_name}</div>
                        <div style={{ fontSize: ".8125rem", color: "var(--color-text-secondary)" }}>
                          {vm.region_display_name} · {vm.vcpus} vCPU · {(vm.ram_mb / 1024).toFixed(0)} GB RAM
                        </div>
                      </div>
                      <div style={{ textAlign: "right", flexShrink: 0 }}>
                        {vm.compliance_pct !== null && (
                          <div style={{ fontSize: ".75rem", color: vm.compliance_pct >= 90 ? "var(--color-success)" : "var(--color-warning)" }}>
                            {vm.compliance_pct.toFixed(0)}% covered
                          </div>
                        )}
                        {vm.last_snapshot_ts && (
                          <div style={{ fontSize: ".75rem", color: "var(--color-text-secondary)" }}>
                            Last: {new Date(vm.last_snapshot_ts).toLocaleDateString()}
                          </div>
                        )}
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
              <div className="section-title" style={{ marginBottom: 0 }}>
                Step 2 — Restore <strong>{selectedVm.vm_name}</strong>
              </div>
            </div>

            {/* Mode selector */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: ".75rem", marginBottom: "1.25rem" }}>
              <button
                className="card"
                style={{
                  textAlign: "left", cursor: "pointer", padding: ".875rem 1rem",
                  border: `2px solid ${mode === "NEW" ? "var(--brand-primary)" : "var(--color-border)"}`,
                  background: mode === "NEW" ? "var(--color-surface-active, var(--color-surface))" : "var(--color-surface)",
                  width: "100%",
                }}
                onClick={() => setMode("NEW")}
              >
                <div style={{ fontWeight: 600, marginBottom: ".3rem" }}>
                  {mode === "NEW" ? "✓ " : ""}Restore to New VM
                </div>
                <div style={{ fontSize: ".8rem", color: "var(--color-text-secondary)" }}>
                  Creates a copy alongside the existing VM. Non-destructive.
                </div>
              </button>
              <button
                className="card"
                style={{
                  textAlign: "left", cursor: "pointer", padding: ".875rem 1rem",
                  border: `2px solid ${mode === "REPLACE" ? "var(--color-error)" : "var(--color-border)"}`,
                  background: mode === "REPLACE" ? "var(--color-surface-active, var(--color-surface))" : "var(--color-surface)",
                  width: "100%",
                }}
                onClick={() => setMode("REPLACE")}
              >
                <div style={{ fontWeight: 600, marginBottom: ".3rem", color: mode === "REPLACE" ? "var(--color-error)" : undefined }}>
                  {mode === "REPLACE" ? "✓ " : ""}Replace VM In-Place
                </div>
                <div style={{ fontSize: ".8rem", color: "var(--color-text-secondary)" }}>
                  Deletes the existing VM and recreates it from the snapshot. Destructive.
                </div>
              </button>
            </div>

            {mode === "NEW" && (
              <div className="info-banner" style={{ marginBottom: "1rem" }}>
                A NEW copy of this VM will be created alongside the existing one. Your running VM is unaffected.
              </div>
            )}
            {mode === "REPLACE" && (
              <div className="error-banner" style={{ marginBottom: "1rem", background: "rgba(255,100,100,.08)" }}>
                ⚠ <strong>Destructive operation:</strong> The existing VM will be deleted before a new one is created from the snapshot. A safety snapshot is automatically taken first.
              </div>
            )}

            {rpLoading && <div className="empty-state"><span className="loading-spinner" /></div>}
            {!rpLoading && restorePoints.length === 0 && (
              <div className="empty-state">No restore points available for this VM.</div>
            )}
            {!rpLoading && restorePoints.map((pt) => (
              <button
                key={pt.snapshot_id}
                className="card"
                style={{ width: "100%", textAlign: "left", cursor: "pointer", padding: ".75rem 1rem", marginBottom: ".5rem", border: "1px solid var(--color-border)", background: "var(--color-surface)" }}
                onClick={() => selectPoint(pt)}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <div style={{ fontWeight: 500, marginBottom: ".15rem" }}>{pt.snapshot_name}</div>
                    <div style={{ fontSize: ".8125rem", color: "var(--color-text-secondary)" }}>
                      {new Date(pt.created_at).toLocaleString()}
                      {pt.size_gb !== null && ` · ${pt.size_gb.toFixed(1)} GB`}
                    </div>
                  </div>
                  <span className={`badge ${pt.status.toLowerCase() === "available" ? "badge-green" : "badge-amber"}`}>
                    {pt.status}
                  </span>
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
                ] as Array<[string, string]>).map(([k, v]) => (
                  <div key={k}>
                    <dt style={{ fontSize: ".7rem", fontWeight: 600, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: ".04em" }}>{k}</dt>
                    <dd style={{ fontSize: ".875rem", color: k === "Mode" && mode === "REPLACE" ? "var(--color-error)" : undefined }}>{v}</dd>
                  </div>
                ))}
              </dl>
            </div>

            {/* NEW mode: new VM name input + optional safety snapshot */}
            {mode === "NEW" && (
              <>
                <div className="field">
                  <label htmlFor="new-vm-name">Name for restored VM</label>
                  <input
                    id="new-vm-name"
                    className="input"
                    type="text"
                    value={newVmName}
                    onChange={(e) => setNewVmName(e.target.value)}
                    disabled={submitting}
                    placeholder="my-vm-restored-2026-04-14"
                  />
                </div>
                <label style={{ display: "flex", alignItems: "flex-start", gap: ".5rem", marginBottom: "1rem", cursor: submitting ? "default" : "pointer", fontWeight: 400, color: "var(--color-text)" }}>
                  <input
                    type="checkbox"
                    checked={safetySnapshot}
                    onChange={(e) => setSafetySnapshot(e.target.checked)}
                    disabled={submitting}
                    style={{ marginTop: ".15rem" }}
                  />
                  <span>
                    <strong>Take a snapshot before restore</strong>
                    <span style={{ display: "block", fontSize: ".8rem", color: "var(--color-text-secondary)" }}>
                      Recommended. Captures the current VM state as a restore point before creating the new copy.
                    </span>
                  </span>
                </label>
              </>
            )}

            {/* REPLACE mode: safety snapshot notice + VM name confirmation */}
            {mode === "REPLACE" && (
              <>
                <div style={{
                  background: "rgba(255,80,80,.07)",
                  border: "1px solid var(--color-error)",
                  borderRadius: "6px",
                  padding: ".875rem 1rem",
                  marginBottom: "1rem",
                }}>
                  <div style={{ fontWeight: 600, color: "var(--color-error)", marginBottom: ".4rem" }}>
                    ⚠ Destructive operation — please read carefully
                  </div>
                  <ul style={{ margin: 0, paddingLeft: "1.2rem", fontSize: ".875rem", lineHeight: 1.6, color: "var(--color-text)" }}>
                    <li>A <strong>safety snapshot</strong> will be taken of the current VM before it is deleted.</li>
                    <li>The existing VM <strong>{selectedVm.vm_name}</strong> will be <strong>permanently deleted</strong>.</li>
                    <li>A new VM will be created from the selected snapshot with the same name.</li>
                    <li>IP addresses will be reassigned according to the IP strategy below.</li>
                  </ul>
                </div>

                <label style={{ display: "flex", alignItems: "flex-start", gap: ".5rem", marginBottom: "1rem", cursor: "pointer", fontWeight: 400, color: "var(--color-text)" }}>
                  <input
                    type="checkbox"
                    checked={safetySnapshot}
                    onChange={(e) => setSafetySnapshot(e.target.checked)}
                    disabled={true}
                    style={{ marginTop: ".15rem" }}
                  />
                  <span>
                    <strong>Take a safety snapshot before deleting</strong>
                    <span style={{ display: "block", fontSize: ".8rem", color: "var(--color-text-secondary)" }}>
                      Mandatory for self-service replace operations. Cannot be disabled.
                    </span>
                  </span>
                </label>

                <div className="field">
                  <label htmlFor="confirm-vm-name">
                    Type <strong>DELETE AND RESTORE {selectedVm.vm_name}</strong> to confirm
                  </label>
                  <input
                    id="confirm-vm-name"
                    className="input"
                    type="text"
                    value={confirmVmName}
                    onChange={(e) => setConfirmVmName(e.target.value)}
                    disabled={submitting}
                    placeholder={`DELETE AND RESTORE ${selectedVm.vm_name}`}
                    autoComplete="off"
                  />
                </div>
              </>
            )}

            {/* Network / IP strategy */}
            {mode === "REPLACE" ? (
              <div style={{ marginBottom: "1rem", padding: ".6rem .875rem", background: "var(--color-surface-elevated, var(--color-surface))", border: "1px solid var(--color-border)", borderRadius: "6px", fontSize: ".875rem" }}>
                <span style={{ fontWeight: 600 }}>IP Strategy: </span>
                <span style={{ color: "var(--color-text-secondary)" }}>Original IPs will be preserved where possible (best-effort). This cannot be changed for in-place replace.</span>
              </div>
            ) : (
              <div className="field" style={{ marginBottom: "1rem" }}>
                <label htmlFor="ip-strategy">IP Strategy</label>
                <select
                  id="ip-strategy"
                  className="select"
                  value={ipStrategy}
                  onChange={(e) => setIpStrategy(e.target.value as "NEW_IPS" | "TRY_SAME_IPS")}
                  disabled={submitting}
                >
                  <option value="NEW_IPS">Allocate new IPs (safest)</option>
                  <option value="TRY_SAME_IPS">Try to keep original IPs (best-effort)</option>
                </select>
              </div>
            )}

            {/* Security groups */}
            {securityGroups.length > 0 && (
              <div style={{ marginBottom: "1rem" }}>
                <div style={{ fontSize: ".8125rem", fontWeight: 600, marginBottom: ".4rem" }}>Security Groups (optional)</div>
                <div style={{ border: "1px solid var(--color-border)", borderRadius: "6px", padding: ".5rem", maxHeight: "140px", overflowY: "auto" }}>
                  {securityGroups.map((sg) => (
                    <label key={sg.id} style={{ display: "flex", alignItems: "center", gap: ".5rem", padding: ".25rem 0", cursor: "pointer", fontSize: ".875rem" }}>
                      <input
                        type="checkbox"
                        checked={selectedSgIds.includes(sg.id)}
                        onChange={(e) => {
                          setSelectedSgIds(prev =>
                            e.target.checked ? [...prev, sg.id] : prev.filter(id => id !== sg.id)
                          );
                        }}
                        disabled={submitting}
                      />
                      <span style={{ fontWeight: 500 }}>{sg.name}</span>
                      {sg.description && (
                        <span style={{ color: "var(--color-text-secondary)", fontSize: ".75rem" }}>{sg.description}</span>
                      )}
                    </label>
                  ))}
                </div>
                <div style={{ fontSize: ".75rem", color: "var(--color-text-secondary)", marginTop: ".2rem" }}>
                  {selectedSgIds.length > 0 ? `${selectedSgIds.length} selected` : "None selected — project default will be used"}
                </div>
              </div>
            )}

            {/* Post-restore storage cleanup */}
            <div style={{ background: "var(--color-surface-elevated, var(--color-surface))", border: "1px solid var(--color-border)", borderRadius: "6px", padding: ".75rem 1rem", marginBottom: "1rem" }}>
              <div style={{ fontSize: ".8125rem", fontWeight: 600, marginBottom: ".5rem" }}>Post-Restore Storage Cleanup (optional)</div>
              {mode === "REPLACE" && (
                <label style={{ display: "flex", alignItems: "flex-start", gap: ".5rem", marginBottom: ".4rem", cursor: submitting ? "default" : "pointer", fontWeight: 400, fontSize: ".875rem" }}>
                  <input
                    type="checkbox"
                    checked={cleanupOldStorage}
                    onChange={(e) => setCleanupOldStorage(e.target.checked)}
                    disabled={submitting}
                    style={{ marginTop: ".15rem" }}
                  />
                  <span>
                    <strong>Delete original VM's volume after restore</strong>
                    <span style={{ display: "block", fontSize: ".8rem", color: "var(--color-text-secondary)" }}>
                      The old root volume becomes orphaned after the VM is deleted. Check this to remove it automatically.
                    </span>
                  </span>
                </label>
              )}
              <label style={{ display: "flex", alignItems: "flex-start", gap: ".5rem", cursor: submitting ? "default" : "pointer", fontWeight: 400, fontSize: ".875rem" }}>
                <input
                  type="checkbox"
                  checked={deleteSourceSnapshot}
                  onChange={(e) => setDeleteSourceSnapshot(e.target.checked)}
                  disabled={submitting}
                  style={{ marginTop: ".15rem" }}
                />
                <span>
                  <strong>Delete source snapshot after restore</strong>
                  <span style={{ display: "block", fontSize: ".8rem", color: "var(--color-text-secondary)" }}>
                    Remove the Cinder snapshot used for this restore once it completes successfully.
                  </span>
                </span>
              </label>
            </div>

            {submitError && <div className="error-banner" style={{ marginBottom: "1rem" }}>{submitError}</div>}

            <button
              className={`btn ${mode === "REPLACE" ? "btn-danger" : "btn-primary"}`}
              style={{ width: "100%", justifyContent: "center" }}
              disabled={
                submitting ||
                (mode === "NEW" && !newVmName.trim()) ||
                (mode === "REPLACE" && confirmVmName !== `DELETE AND RESTORE ${selectedVm.vm_name}`)
              }
              onClick={handleExecute}
            >
              {submitting
                ? <span className="loading-spinner" />
                : mode === "REPLACE"
                  ? "Replace VM (Destructive)"
                  : "Start Restore"
              }
            </button>
          </div>
        )}
      </div>

      {/* ── Right: Job panels ── */}
      <div>
        <div className="section-title">Active Jobs</div>
        {activeJobs.length === 0 ? (
          <div className="card empty-state" style={{ padding: "1.25rem", marginBottom: "1.25rem" }}>
            No active restore jobs.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: ".75rem", marginBottom: "1.25rem" }}>
            {activeJobs.map((job) => (
              <div key={job.job_id} className="card" style={{ padding: "1rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: ".35rem" }}>
                  <div style={{ fontWeight: 600, fontSize: ".875rem" }}>{job.vm_name}</div>
                  <div style={{ display: "flex", gap: ".4rem", alignItems: "center" }}>
                    {job.mode === "REPLACE" && (
                      <span className="badge badge-red" style={{ fontSize: ".7rem" }}>Replace</span>
                    )}
                    <JobStatusBadge status={job.status} />
                  </div>
                </div>
                <div style={{ fontSize: ".8rem", color: "var(--color-text-secondary)", marginBottom: ".5rem" }}>
                  {job.mode === "REPLACE"
                    ? `In-place replace · ${job.region_display_name}`
                    : `→ ${job.new_vm_name} · ${job.region_display_name}`}
                </div>
                <div className="progress-track" style={{ marginBottom: ".35rem" }}>
                  <div className="progress-fill" style={{ width: `${job.progress_pct}%` }} />
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: ".75rem" }}>
                  <span style={{ color: "var(--color-text-secondary)" }}>{job.progress_pct}%</span>
                  {job.status.toLowerCase() === "pending" && (
                    <button
                      className="btn btn-danger"
                      style={{ fontSize: ".75rem", padding: ".2rem .5rem" }}
                      disabled={cancellingId === job.job_id}
                      onClick={() => handleCancel(job.job_id)}
                    >
                      Cancel
                    </button>
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
            {completedJobs.slice(0, 10).map((job) => (
              <div key={job.job_id} className="card" style={{ padding: ".75rem 1rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: ".5rem" }}>
                  <div>
                    <div style={{ fontWeight: 500, fontSize: ".875rem" }}>{job.vm_name}</div>
                    <div style={{ fontSize: ".75rem", color: "var(--color-text-secondary)" }}>
                      {job.mode === "REPLACE" ? "Replace in-place" : `→ ${job.new_vm_name}`}
                      {" · "}{new Date(job.updated_at).toLocaleString()}
                      {(job.failure_reason || job.error_message) && (
                        <span style={{ color: "var(--color-error)", marginLeft: ".4rem" }}>
                          · {job.failure_reason || job.error_message}
                        </span>
                      )}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: ".4rem", alignItems: "center", flexShrink: 0 }}>
                    {job.mode === "REPLACE" && (
                      <span className="badge badge-red" style={{ fontSize: ".7rem" }}>Replace</span>
                    )}
                    <JobStatusBadge status={job.status} />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
