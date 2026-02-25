/**
 * ProjectSetup — Configure migration project topology, upload RVTools,
 *                set bandwidth parameters and agent profiles.
 *
 *  Features:
 *    • Contextual tooltips on every field (hover ⓘ for guidance)
 *    • Edit-after-save: settings are always editable; change & re-save
 *    • "Re-assess" button when assessment already ran — re-scores all VMs
 */

import React, { useState, useCallback, useMemo } from "react";
import { API_BASE } from "../../config";
import type { MigrationProject } from "../MigrationPlannerTab";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function getToken(): string | null {
  return localStorage.getItem("auth_token");
}

async function apiFetch<T>(path: string, opts?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(opts?.headers as Record<string, string> || {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  if (!(opts?.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `API error ${res.status}`);
  }
  return res.json();
}

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Props {
  project: MigrationProject;
  onProjectUpdated: (p: MigrationProject) => void;
  onNavigate: (view: string) => void;
}

type TopologyType = "local" | "cross_site_dedicated" | "cross_site_internet";

/* ------------------------------------------------------------------ */
/*  Tooltip map — contextual help for each field                       */
/* ------------------------------------------------------------------ */

const TIPS: Record<string, string> = {
  srcNic:
    "Speed of the physical NIC on your VMware ESXi hosts (e.g. 10 Gbps, 25 Gbps). " +
    "Find this in vCenter → Host → Configure → Networking → Physical Adapters, or from the RVTools 'vHost' sheet.",
  srcPct:
    "Percentage of source NIC bandwidth you're willing to dedicate to migration traffic. " +
    "Use 30-40 % for production hosts with live workloads; up to 80 % during a maintenance window.",
  linkSpeed:
    "Capacity of the dedicated WAN link between your VMware site and the PCD site " +
    "(e.g. MPLS circuit, dark fiber, VPN tunnel). Check with your network team or ISP contract.",
  linkPct:
    "Usable share of the dedicated link for migration. Reserve headroom for other traffic " +
    "(management, DNS, monitoring). Typical: 60-80 %.",
  srcUpload:
    "Upload bandwidth from your VMware site to the internet, in Mbps. " +
    "Run a speed test from the VMware management network or check your ISP SLA.",
  dstDownload:
    "Download bandwidth at the PCD / MSP site, in Mbps. Ask your MSP for the committed ingress rate.",
  rtt:
    "Round-trip latency between the two sites. Measure with `ping` from a VMware host to the PCD gateway. " +
    "Higher RTT degrades TCP throughput for internet-based migrations.",
  tgtNic:
    "Speed of the NIC on PCD hypervisor nodes that will receive migration traffic " +
    "(e.g. 10 Gbps, 25 Gbps). Found in PCD → Infrastructure → Host details.",
  tgtPct:
    "Percentage of the PCD NIC you can allocate to ingest. If PCD is already running workloads, keep this " +
    "at 30-40 %; if it's a fresh deployment, 70-80 % is safe.",
  storageMbps:
    "Sustained sequential write speed of your PCD storage backend (Ceph, NetApp, etc.) in MB/s. " +
    "Get this from a `fio` benchmark on the PCD storage pool, or from the storage vendor's spec sheet. " +
    "This is often the migration bottleneck.",
  agentCount:
    "Number of vJailbreak migration agent VMs to deploy on PCD. More agents = more parallel streams. " +
    "Start with 2 and scale up based on the sizing recommendation below.",
  agentConcurrent:
    "How many VMs each agent migrates concurrently. Higher values need more agent RAM. " +
    "Default 5 is a good starting point; raise to 8-10 for small VMs, lower to 2-3 for very large VMs.",
  agentNic:
    "NIC speed assigned to each vJailbreak agent VM on PCD (typically 10 Gbps virtio). " +
    "Check the agent VM definition in your PCD tenant.",
  agentNicPct:
    "Usable share of the agent's NIC bandwidth. Agents are dedicated so 70-80 % is typical.",
  durationDays:
    "Total calendar duration of the migration project in days. Used together with working hours " +
    "to estimate how many agents are needed.",
  workingHours:
    "Hours per day during which migration traffic runs. E.g. 24 for non-stop, 8 for business hours only, " +
    "4 for nights-only.",
  workingDays:
    "Working days per week (1-7). Use 5 for weekdays only, 7 for continuous migration.",
  targetVmsDay:
    "Override: desired VMs migrated per day. If set, the scheduler derives agent count from this target. " +
    "Leave at 0 to let the system calculate from project duration.",
  /* Bandwidth Constraint Model card explanations */
  bwSourceOut:
    "Effective outbound bandwidth from your VMware ESXi source hosts, after applying the usable-percentage cap. " +
    "Calculated as Source NIC speed × Source usable %. This is often the bottleneck for hosts with 10 GbE NICs.",
  bwTransport:
    "Effective bandwidth of the transport link between your VMware site and the PCD site. " +
    "For dedicated links: Link Speed × usable %. For internet: min(upload, download) × RTT penalty. " +
    "Shows N/A for local (same-DC) topology.",
  bwAgentIngest:
    "Total ingest bandwidth across all vJailbreak migration agents on the PCD side. " +
    "Calculated as Agent NIC × Agent NIC usable % × Agent count. Scale up by adding more agents.",
  bwStorageWrite:
    "Effective PCD storage write throughput converted to Mbps (MB/s × 8). " +
    "This reflects how fast your Ceph/NetApp/SAN backend can sustain sequential writes during migration.",
  bwBottleneck:
    "The constraint with the lowest effective Mbps is the migration bottleneck. " +
    "Improving the bottleneck component will have the most impact on overall migration speed.",
};

/* ------------------------------------------------------------------ */
/*  FieldLabel — label + info tooltip                                  */
/* ------------------------------------------------------------------ */

function FieldLabel({ text, tip }: { text: string; tip?: string }) {
  const [show, setShow] = useState(false);
  return (
    <label style={labelStyle}>
      {text}
      {tip && (
        <span
          style={{
            position: "relative", display: "inline-block", marginLeft: 6,
            cursor: "help", color: "#3b82f6", fontWeight: 700, fontSize: "0.8rem",
          }}
          onMouseEnter={() => setShow(true)}
          onMouseLeave={() => setShow(false)}
        >
          ⓘ
          {show && (
            <span style={tooltipStyle}>{tip}</span>
          )}
        </span>
      )}
    </label>
  );
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function ProjectSetup({ project, onProjectUpdated, onNavigate }: Props) {
  const [saving, setSaving] = useState(false);
  const [reassessing, setReassessing] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [uploading, setUploading] = useState(false);
  const [clearing, setClearing] = useState(false);

  /* ---- Topology settings (local state mirrors project) ---- */
  const [topology, setTopology] = useState<TopologyType>(project.topology_type as TopologyType);
  const [srcNic, setSrcNic] = useState(project.source_nic_speed_gbps);
  const [srcPct, setSrcPct] = useState(project.source_usable_pct);
  const [linkSpeed, setLinkSpeed] = useState(project.link_speed_gbps || 1);
  const [linkPct, setLinkPct] = useState(project.link_usable_pct);
  const [srcUpload, setSrcUpload] = useState(project.source_upload_mbps || 100);
  const [dstDownload, setDstDownload] = useState(project.dest_download_mbps || 100);
  const [rtt, setRtt] = useState(project.rtt_category || "lt5");
  const [tgtNic, setTgtNic] = useState(project.target_ingress_speed_gbps);
  const [tgtPct, setTgtPct] = useState(project.target_usable_pct);
  const [storageMbps, setStorageMbps] = useState(project.pcd_storage_write_mbps);

  /* ---- Agent profile ---- */
  const [agentCount, setAgentCount] = useState(project.agent_count);
  const [agentConcurrent, setAgentConcurrent] = useState(project.agent_concurrent_vms);
  const [agentNic, setAgentNic] = useState(project.agent_nic_speed_gbps);
  const [agentNicPct, setAgentNicPct] = useState(project.agent_nic_usable_pct);

  /* ---- Schedule settings ---- */
  const [durationDays, setDurationDays] = useState(project.migration_duration_days || 30);
  const [workingHours, setWorkingHours] = useState(project.working_hours_per_day || 8);
  const [workingDays, setWorkingDays] = useState(project.working_days_per_week || 5);
  const [targetVmsDay, setTargetVmsDay] = useState(project.target_vms_per_day || 0);

  /* ---- Bandwidth model (fetched on load, but live computations override display) ---- */
  const [, setBwModel] = useState<any>(null);
  const [, setAgentRec] = useState<any>(null);

  /* ---- Dirty tracking: has the user changed anything since last save? ---- */
  const isDirty =
    topology !== (project.topology_type as TopologyType) ||
    srcNic !== project.source_nic_speed_gbps ||
    srcPct !== project.source_usable_pct ||
    tgtNic !== project.target_ingress_speed_gbps ||
    tgtPct !== project.target_usable_pct ||
    storageMbps !== project.pcd_storage_write_mbps ||
    agentCount !== project.agent_count ||
    agentConcurrent !== project.agent_concurrent_vms ||
    agentNic !== project.agent_nic_speed_gbps ||
    agentNicPct !== project.agent_nic_usable_pct ||
    (topology === "cross_site_dedicated" && linkSpeed !== (project.link_speed_gbps || 1)) ||
    (topology === "cross_site_dedicated" && linkPct !== project.link_usable_pct) ||
    (topology === "cross_site_internet" && srcUpload !== (project.source_upload_mbps || 100)) ||
    (topology === "cross_site_internet" && dstDownload !== (project.dest_download_mbps || 100)) ||
    (topology === "cross_site_internet" && rtt !== (project.rtt_category || "lt5"));

  /* Schedule dirty checks */
  const isScheduleDirty =
    durationDays !== (project.migration_duration_days || 30) ||
    workingHours !== (project.working_hours_per_day || 8) ||
    workingDays !== (project.working_days_per_week || 5) ||
    targetVmsDay !== (project.target_vms_per_day || 0);

  const isDirtyFinal = isDirty || isScheduleDirty;

  /* Is there an existing assessment that would need re-running? */
  const hasAssessment = project.status === "assessment" ||
    (project.risk_summary && Object.keys(project.risk_summary).length > 0);

  /* ---- Save settings ---- */
  const handleSave = async () => {
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const body: Record<string, any> = {
        topology_type: topology,
        source_nic_speed_gbps: srcNic,
        source_usable_pct: srcPct,
        target_ingress_speed_gbps: tgtNic,
        target_usable_pct: tgtPct,
        pcd_storage_write_mbps: storageMbps,
        agent_count: agentCount,
        agent_concurrent_vms: agentConcurrent,
        agent_nic_speed_gbps: agentNic,
        agent_nic_usable_pct: agentNicPct,
        migration_duration_days: durationDays,
        working_hours_per_day: workingHours,
        working_days_per_week: workingDays,
        target_vms_per_day: targetVmsDay || null,
      };
      if (topology === "cross_site_dedicated") {
        body.link_speed_gbps = linkSpeed;
        body.link_usable_pct = linkPct;
      }
      if (topology === "cross_site_internet") {
        body.source_upload_mbps = srcUpload;
        body.dest_download_mbps = dstDownload;
        body.rtt_category = rtt;
        body.link_usable_pct = linkPct;
      }
      const data = await apiFetch<{ project: MigrationProject }>(
        `/api/migration/projects/${project.project_id}`,
        { method: "PATCH", body: JSON.stringify(body) }
      );
      onProjectUpdated(data.project);
      setSuccess("Settings saved ✓");
      // Refresh bandwidth model
      loadBandwidthModel();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  /* ---- Save + Re-assess in one click ---- */
  const handleSaveAndReassess = async () => {
    setReassessing(true);
    setError("");
    setSuccess("");
    try {
      // 1. Save updated settings
      const body: Record<string, any> = {
        topology_type: topology,
        source_nic_speed_gbps: srcNic,
        source_usable_pct: srcPct,
        target_ingress_speed_gbps: tgtNic,
        target_usable_pct: tgtPct,
        pcd_storage_write_mbps: storageMbps,
        agent_count: agentCount,
        agent_concurrent_vms: agentConcurrent,
        agent_nic_speed_gbps: agentNic,
        agent_nic_usable_pct: agentNicPct,
        migration_duration_days: durationDays,
        working_hours_per_day: workingHours,
        working_days_per_week: workingDays,
        target_vms_per_day: targetVmsDay || null,
      };
      if (topology === "cross_site_dedicated") {
        body.link_speed_gbps = linkSpeed;
        body.link_usable_pct = linkPct;
      }
      if (topology === "cross_site_internet") {
        body.source_upload_mbps = srcUpload;
        body.dest_download_mbps = dstDownload;
        body.rtt_category = rtt;
        body.link_usable_pct = linkPct;
      }
      await apiFetch<{ project: MigrationProject }>(
        `/api/migration/projects/${project.project_id}`,
        { method: "PATCH", body: JSON.stringify(body) }
      );

      // 2. Re-run assessment
      await apiFetch<any>(
        `/api/migration/projects/${project.project_id}/assess`,
        { method: "POST" }
      );

      // 3. Refresh project
      const refreshed = await apiFetch<{ project: MigrationProject }>(
        `/api/migration/projects/${project.project_id}`
      );
      onProjectUpdated(refreshed.project);
      loadBandwidthModel();
      setSuccess("Settings saved & assessment re-run ✓ — migration times and risk scores updated.");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setReassessing(false);
    }
  };

  /* ---- Upload RVTools ---- */
  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError("");
    setSuccess("");
    try {
      const formData = new FormData();
      formData.append("file", file);
      const data = await apiFetch<{ stats: Record<string, number> }>(
        `/api/migration/projects/${project.project_id}/upload`,
        { method: "POST", body: formData }
      );
      setSuccess(`Uploaded: ${Object.entries(data.stats).map(([k, v]) => `${k}: ${v}`).join(", ")}`);
      // Refresh project
      const proj = await apiFetch<{ project: MigrationProject }>(`/api/migration/projects/${project.project_id}`);
      onProjectUpdated(proj.project);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  /* ---- Clear RVTools data ---- */
  const handleClear = async () => {
    if (!confirm("Delete all uploaded RVTools data? This will reset the project to draft and remove all VMs, tenants, hosts, clusters, and assessment results. Project settings will be preserved.")) return;
    setClearing(true);
    setError("");
    setSuccess("");
    try {
      await apiFetch<any>(
        `/api/migration/projects/${project.project_id}/rvtools`,
        { method: "DELETE" }
      );
      // Refresh project (status will be 'draft')
      const proj = await apiFetch<{ project: MigrationProject }>(`/api/migration/projects/${project.project_id}`);
      onProjectUpdated(proj.project);
      setSuccess("RVTools data cleared. Project reset to draft.");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setClearing(false);
    }
  };

  /* ---- Bandwidth model ---- */
  const loadBandwidthModel = useCallback(async () => {
    try {
      const data = await apiFetch<{ bandwidth: any }>(`/api/migration/projects/${project.project_id}/bandwidth`);
      setBwModel(data.bandwidth);
    } catch { /* ignore if no data yet */ }
    try {
      const data = await apiFetch<{ recommendation: any }>(`/api/migration/projects/${project.project_id}/agent-recommendation`);
      setAgentRec(data.recommendation);
    } catch { /* ignore */ }
  }, [project.project_id]);

  React.useEffect(() => { loadBandwidthModel(); }, [loadBandwidthModel]);

  /* ---- Client-side LIVE bandwidth computation (mirrors migration_engine) ---- */
  const liveBw = useMemo(() => {
    const gbpsToMbps = (g: number) => g * 1000;
    const applyPct = (mbps: number, pct: number) => mbps * (pct / 100);

    const sourceEff = applyPct(gbpsToMbps(srcNic), srcPct);

    let linkEff: number | null = null;
    if (topology === "cross_site_dedicated") {
      linkEff = applyPct(gbpsToMbps(linkSpeed), linkPct);
    } else if (topology === "cross_site_internet") {
      const rawLink = Math.min(srcUpload, dstDownload);
      // RTT penalty (matches backend migration_engine.py)
      const rttPenalty: Record<string, number> = { lt5: 1.0, "5-20": 0.90, "20-50": 0.75, "50-100": 0.55, gt100: 0.35 };
      linkEff = applyPct(rawLink, linkPct) * (rttPenalty[rtt] ?? 0.75);
    }

    const agentEff = applyPct(gbpsToMbps(agentNic), agentNicPct) * agentCount;
    const storageEff = storageMbps * 8.0; // MB/s → Mbps

    // Find bottleneck
    const constraints: [string, number][] = [
      ["source_host_nic", sourceEff],
      ["agent_ingest", agentEff],
      ["pcd_storage", storageEff],
    ];
    if (linkEff !== null) {
      constraints.push(["transport_link", linkEff]);
    }

    const [bottleneck, bottleneckMbps] = constraints.reduce(
      (min, cur) => (cur[1] < min[1] ? cur : min),
      constraints[0]
    );

    return {
      source_effective_mbps: Math.round(sourceEff),
      link_effective_mbps: linkEff !== null ? Math.round(linkEff) : null,
      agent_effective_mbps: Math.round(agentEff),
      storage_effective_mbps: Math.round(storageEff),
      bottleneck,
      bottleneck_mbps: Math.round(bottleneckMbps),
    };
  }, [topology, srcNic, srcPct, linkSpeed, linkPct, srcUpload, dstDownload, rtt,
      tgtNic, tgtPct, storageMbps, agentCount, agentNic, agentNicPct]);

  /* ---- Client-side LIVE agent sizing (mirrors migration_engine.recommend_agent_sizing) ---- */
  const vmCount = project.totals?.total_vms ?? project.vm_count ?? 0;
  const totalDiskGb = Number(project.totals?.total_disk_gb ?? 0);

  const liveAgent = useMemo(() => {
    const concurrent = agentConcurrent;
    const reasoning: string[] = [];
    let recommended: number;

    if (targetVmsDay > 0) {
      const slotsPerDay = workingHours / 2.0;
      const vmsPerAgentPerDay = concurrent * slotsPerDay;
      recommended = Math.max(2, Math.ceil(targetVmsDay / vmsPerAgentPerDay));
      reasoning.push(`Target: ${targetVmsDay} VMs/day → ~${vmsPerAgentPerDay.toFixed(0)} VMs/agent/day → ${recommended} agents`);
    } else if (durationDays > 0) {
      const totalWeeks = durationDays / 7.0;
      const effectiveDays = Math.max(1, totalWeeks * workingDays);
      const vmsPerDayNeeded = vmCount / effectiveDays;
      const slotsPerDay = workingHours / 2.0;
      const vmsPerAgentPerDay = concurrent * slotsPerDay;
      recommended = Math.max(2, Math.ceil(vmsPerDayNeeded / vmsPerAgentPerDay));
      reasoning.push(
        `${vmCount} VMs in ${durationDays} days (${workingDays}d/wk × ${workingHours}h/d = ${effectiveDays.toFixed(0)} effective days)`
      );
      reasoning.push(`Need ${vmsPerDayNeeded.toFixed(1)} VMs/day → ${recommended} agents`);
    } else {
      recommended = Math.max(2, Math.ceil(vmCount / (concurrent * 4)));
      reasoning.push(`${vmCount} VMs total, ${concurrent} concurrent per agent`);
    }

    const vcpu = 2 * concurrent;
    const ram = 2 + 1 * concurrent;
    reasoning.push(`Recommended ${recommended} agents = ${recommended * concurrent} concurrent slots`);
    reasoning.push(`Per agent: ${vcpu} vCPU, ${ram} GB RAM, 0 GB disk`);

    if (durationDays > 0) {
      const effectiveDays = Math.max(1, (durationDays / 7.0) * workingDays);
      const slotsPerDay = workingHours / 2.0;
      const dailyCapacity = recommended * concurrent * slotsPerDay;
      const estDays = dailyCapacity > 0 ? vmCount / dailyCapacity : 999;
      reasoning.push(`Estimated completion: ~${estDays.toFixed(0)} working days (${dailyCapacity.toFixed(0)} VMs/day capacity)`);
    }

    return { recommended_agent_count: recommended, vcpu_per_agent: vcpu, ram_gb_per_agent: ram, disk_gb_per_agent: 0, reasoning };
  }, [vmCount, agentConcurrent, durationDays, workingHours, workingDays, targetVmsDay]);

  /* ---- Storage feasibility analysis ---- */
  const feasibility = useMemo(() => {
    const bottleneckMbps = liveBw.bottleneck_mbps;
    if (bottleneckMbps <= 0 || totalDiskGb <= 0) return null;

    // bottleneck_mbps is in Megabits/s; convert to GB/hour
    // Mbps → MB/s = ÷8; MB/s → GB/s = ÷1024; GB/s → GB/h = ×3600
    const gbPerHour = (bottleneckMbps / 8) * 3600 / 1024;
    const totalTb = totalDiskGb / 1024;
    const rawTransferHours = totalDiskGb / gbPerHour;

    // If schedule defined, compute available hours
    let availableHours = 0;
    let effectiveDays = 0;
    if (durationDays > 0) {
      const totalWeeks = durationDays / 7.0;
      effectiveDays = Math.max(1, totalWeeks * workingDays);
      availableHours = effectiveDays * workingHours;
    }

    const transferDaysNeeded = rawTransferHours / workingHours; // in working days
    const feasible = availableHours > 0 ? rawTransferHours <= availableHours : true;
    const utilizationPct = availableHours > 0 ? (rawTransferHours / availableHours) * 100 : 0;

    return {
      totalTb,
      bottleneckMbps,
      gbPerHour,
      rawTransferHours,
      transferDaysNeeded: Math.ceil(transferDaysNeeded),
      availableHours,
      effectiveDays: Math.round(effectiveDays),
      feasible,
      utilizationPct: Math.round(utilizationPct),
      overrunDays: availableHours > 0 ? Math.ceil((rawTransferHours - availableHours) / workingHours) : 0,
    };
  }, [liveBw.bottleneck_mbps, totalDiskGb, durationDays, workingDays, workingHours]);

  /* ================================================================ */
  /*  Render                                                          */
  /* ================================================================ */
  return (
    <div style={{ maxWidth: 1000 }}>
      <h2 style={{ marginTop: 0 }}>Project Setup — {project.name}</h2>

      {error && <div style={alertError}>{error}</div>}
      {success && <div style={alertSuccess}>{success}</div>}

      {/* ---- RVTools Upload ---- */}
      <section style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>📁 VMware RVTools Upload</h3>
        {project.rvtools_filename ? (
          <div>
            <p style={{ margin: 0 }}>
              ✅ <strong>{project.rvtools_filename}</strong> uploaded at {new Date(project.rvtools_uploaded_at || "").toLocaleString()}
            </p>

            {/* Sheet row counts */}
            {project.rvtools_sheet_stats && (
              <div style={{ marginTop: 12 }}>
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
                  {["vInfo", "vDisk", "vNIC", "vHost", "vCluster", "vSnapshot"].map(key => {
                    const val = project.rvtools_sheet_stats[key];
                    return val != null ? (
                      <span key={key} style={badgeStyle}>{key}: {val}</span>
                    ) : null;
                  })}
                </div>

                {/* Power state breakdown */}
                {project.rvtools_sheet_stats.power_states && (
                  <div style={miniCardRow}>
                    <span style={{ fontWeight: 600, fontSize: "0.85rem", marginRight: 4 }}>⚡ Power State:</span>
                    {Object.entries(project.rvtools_sheet_stats.power_states as Record<string, number>).map(([state, cnt]) => (
                      <span key={state} style={{
                        ...badgeStyle,
                        background: state === "poweredon" ? "#dcfce7" : state === "poweredoff" ? "#fee2e2" : "#fef9c3",
                        borderColor: state === "poweredon" ? "#86efac" : state === "poweredoff" ? "#fca5a5" : "#fde68a",
                      }}>
                        {state === "poweredon" ? "🟢 Powered On" : state === "poweredoff" ? "🔴 Powered Off" : `⏸️ ${state}`}: {cnt}
                      </span>
                    ))}
                    {project.rvtools_sheet_stats.templates > 0 && (
                      <span style={{ ...badgeStyle, background: "#f3f4f6" }}>📋 Templates: {project.rvtools_sheet_stats.templates}</span>
                    )}
                  </div>
                )}

                {/* OS family breakdown */}
                {project.rvtools_sheet_stats.os_families && (
                  <div style={miniCardRow}>
                    <span style={{ fontWeight: 600, fontSize: "0.85rem", marginRight: 4 }}>💻 OS Families:</span>
                    {Object.entries(project.rvtools_sheet_stats.os_families as Record<string, number>)
                      .sort(([,a], [,b]) => (b as number) - (a as number))
                      .map(([family, cnt]) => (
                        <span key={family} style={{
                          ...badgeStyle,
                          background: family === "windows" ? "#dbeafe" : family === "linux" ? "#fef3c7" : "#f3f4f6",
                          borderColor: family === "windows" ? "#93c5fd" : family === "linux" ? "#fcd34d" : "#e5e7eb",
                        }}>
                          {family === "windows" ? "🪟" : family === "linux" ? "🐧" : "❓"} {family}: {cnt}
                        </span>
                      ))}
                  </div>
                )}

                {/* Tenant / vCD info */}
                {(project.rvtools_sheet_stats.tenants > 0 || project.rvtools_sheet_stats.vcd_detected) && (
                  <div style={miniCardRow}>
                    <span style={{ fontWeight: 600, fontSize: "0.85rem", marginRight: 4 }}>🏢 Tenants:</span>
                    <span style={badgeStyle}>{project.rvtools_sheet_stats.tenants} detected</span>
                    {project.rvtools_sheet_stats.vcd_detected && (
                      <span style={{ ...badgeStyle, background: "#ede9fe", borderColor: "#c4b5fd", fontWeight: 600 }}>
                        ☁️ VMware Cloud Director detected
                      </span>
                    )}
                  </div>
                )}
              </div>
            )}

            <p style={{ fontSize: "0.85rem", color: "#6b7280", marginTop: 8 }}>
              Upload again to replace all source data (re-import).
            </p>
            <button onClick={handleClear} disabled={clearing}
              style={{ marginTop: 8, padding: "6px 14px", borderRadius: 6, border: "1px solid #fca5a5",
                background: "#fef2f2", color: "#dc2626", cursor: "pointer", fontWeight: 600, fontSize: "0.85rem" }}>
              {clearing ? "Clearing..." : "🗑️ Clear RVTools Data"}
            </button>
          </div>
        ) : (
          <p style={{ color: "#6b7280" }}>Upload a VMware RVTools XLSX export to begin analysis.</p>
        )}
        <div style={{ marginTop: 8 }}>
          <label style={btnPrimary as any}>
            {uploading ? "Uploading..." : "📤 Upload VMware RVTools XLSX"}
            <input type="file" accept=".xlsx,.xls" onChange={handleUpload} disabled={uploading}
              style={{ display: "none" }} />
          </label>
        </div>
      </section>

      {/* ---- Topology ---- */}
      <section style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>🌐 Migration Topology</h3>
        <div style={{ display: "flex", gap: 12, marginBottom: 16 }}>
          {(["local", "cross_site_dedicated", "cross_site_internet"] as TopologyType[]).map(t => (
            <label key={t} style={{
              padding: "10px 16px", borderRadius: 8, cursor: "pointer",
              border: topology === t ? "2px solid #3b82f6" : "1px solid var(--border, #d1d5db)",
              background: topology === t ? "#eff6ff" : "transparent",
              flex: 1, textAlign: "center",
            }}>
              <input type="radio" name="topology" value={t} checked={topology === t}
                onChange={() => setTopology(t)} style={{ display: "none" }} />
              <div style={{ fontWeight: 600 }}>
                {t === "local" ? "🏢 Local (Same DC)" :
                 t === "cross_site_dedicated" ? "🔗 Cross-site (Dedicated link)" :
                 "🌍 Cross-site (Internet)"}
              </div>
              <div style={{ fontSize: "0.8rem", color: "#6b7280", marginTop: 4 }}>
                {t === "local" ? "VMware & PCD in same broadcast domain" :
                 t === "cross_site_dedicated" ? "MPLS / dark fiber / VPN" :
                 "Public internet / ISP link"}
              </div>
            </label>
          ))}
        </div>

        {/* Source side */}
        <h4>Source (VMware) Side</h4>
        <div style={rowStyle}>
          <div style={fieldStyle}>
            <FieldLabel text="Source Host NIC Speed (Gbps)" tip={TIPS.srcNic} />
            <input type="number" value={srcNic} onChange={e => setSrcNic(+e.target.value)} style={inputStyle} min={0.1} step={0.1} />
          </div>
          <div style={fieldStyle}>
            <FieldLabel text="Usable % for Migration" tip={TIPS.srcPct} />
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input type="range" min={10} max={90} value={srcPct} onChange={e => setSrcPct(+e.target.value)} style={{ flex: 1 }} />
              <span style={{ minWidth: 40, textAlign: "right", fontWeight: 600 }}>{srcPct}%</span>
            </div>
          </div>
        </div>

        {/* Transport link — cross-site dedicated */}
        {topology === "cross_site_dedicated" && (
          <>
            <h4>Dedicated Link</h4>
            <div style={rowStyle}>
              <div style={fieldStyle}>
                <FieldLabel text="Link Speed (Gbps)" tip={TIPS.linkSpeed} />
                <input type="number" value={linkSpeed} onChange={e => setLinkSpeed(+e.target.value)} style={inputStyle} min={0.01} step={0.1} />
              </div>
              <div style={fieldStyle}>
                <FieldLabel text="Usable %" tip={TIPS.linkPct} />
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input type="range" min={10} max={90} value={linkPct} onChange={e => setLinkPct(+e.target.value)} style={{ flex: 1 }} />
                  <span style={{ minWidth: 40, textAlign: "right", fontWeight: 600 }}>{linkPct}%</span>
                </div>
              </div>
            </div>
          </>
        )}

        {/* Transport link — internet */}
        {topology === "cross_site_internet" && (
          <>
            <h4>Internet / ISP Link</h4>
            <div style={rowStyle}>
              <div style={fieldStyle}>
                <FieldLabel text="Source Upload (Mbps)" tip={TIPS.srcUpload} />
                <input type="number" value={srcUpload} onChange={e => setSrcUpload(+e.target.value)} style={inputStyle} min={1} />
              </div>
              <div style={fieldStyle}>
                <FieldLabel text="MSP Download (Mbps)" tip={TIPS.dstDownload} />
                <input type="number" value={dstDownload} onChange={e => setDstDownload(+e.target.value)} style={inputStyle} min={1} />
              </div>
            </div>
            <div style={rowStyle}>
              <div style={fieldStyle}>
                <FieldLabel text="Estimated RTT" tip={TIPS.rtt} />
                <select value={rtt} onChange={e => setRtt(e.target.value)} style={inputStyle}>
                  <option value="lt5">&lt; 5ms (same city)</option>
                  <option value="5-20">5-20ms (same country)</option>
                  <option value="20-50">20-50ms (cross-country)</option>
                  <option value="50-100">50-100ms (intercontinental)</option>
                  <option value="gt100">&gt; 100ms (far / satellite)</option>
                </select>
              </div>
              <div style={fieldStyle}>
                <FieldLabel text="Usable %" tip={TIPS.linkPct} />
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input type="range" min={10} max={90} value={linkPct} onChange={e => setLinkPct(+e.target.value)} style={{ flex: 1 }} />
                  <span style={{ minWidth: 40, textAlign: "right", fontWeight: 600 }}>{linkPct}%</span>
                </div>
              </div>
            </div>
          </>
        )}

        {/* PCD / Target side */}
        <h4>PCD (Target) Side</h4>
        <div style={rowStyle}>
          <div style={fieldStyle}>
            <FieldLabel text="Target Ingress NIC (Gbps)" tip={TIPS.tgtNic} />
            <input type="number" value={tgtNic} onChange={e => setTgtNic(+e.target.value)} style={inputStyle} min={0.1} step={0.1} />
          </div>
          <div style={fieldStyle}>
            <FieldLabel text="Usable %" tip={TIPS.tgtPct} />
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input type="range" min={10} max={90} value={tgtPct} onChange={e => setTgtPct(+e.target.value)} style={{ flex: 1 }} />
              <span style={{ minWidth: 40, textAlign: "right", fontWeight: 600 }}>{tgtPct}%</span>
            </div>
          </div>
        </div>
        <div style={rowStyle}>
          <div style={fieldStyle}>
            <FieldLabel text="PCD Storage Write (MB/s)" tip={TIPS.storageMbps} />
            <input type="number" value={storageMbps} onChange={e => setStorageMbps(+e.target.value)} style={inputStyle} min={10} />
          </div>
          <div style={fieldStyle}></div>
        </div>
      </section>

      {/* ---- Agent Profile ---- */}
      <section style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>🤖 vJailbreak Agent Profile</h3>
        <p style={{ color: "#6b7280", fontSize: "0.85rem", marginTop: 0 }}>
          Agents are deployed on the PCD side and pull data from VMware source hosts.
        </p>
        <div style={rowStyle}>
          <div style={fieldStyle}>
            <FieldLabel text="Number of Agents" tip={TIPS.agentCount} />
            <input type="number" value={agentCount} onChange={e => setAgentCount(+e.target.value)} style={inputStyle} min={1} max={50} />
          </div>
          <div style={fieldStyle}>
            <FieldLabel text="Concurrent VMs per Agent" tip={TIPS.agentConcurrent} />
            <input type="number" value={agentConcurrent} onChange={e => setAgentConcurrent(+e.target.value)} style={inputStyle} min={1} max={20} />
          </div>
        </div>
        <div style={rowStyle}>
          <div style={fieldStyle}>
            <FieldLabel text="Agent NIC Speed (Gbps)" tip={TIPS.agentNic} />
            <input type="number" value={agentNic} onChange={e => setAgentNic(+e.target.value)} style={inputStyle} min={0.1} step={0.1} />
          </div>
          <div style={fieldStyle}>
            <FieldLabel text="Agent NIC Usable %" tip={TIPS.agentNicPct} />
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input type="range" min={10} max={95} value={agentNicPct} onChange={e => setAgentNicPct(+e.target.value)} style={{ flex: 1 }} />
              <span style={{ minWidth: 40, textAlign: "right", fontWeight: 600 }}>{agentNicPct}%</span>
            </div>
          </div>
        </div>

        <div style={{ marginTop: 8, padding: 12, background: "#f0f4ff", borderRadius: 6, fontSize: "0.85rem" }}>
          <strong>Total concurrent slots:</strong> {agentCount * agentConcurrent} VMs
        </div>

        {/* Agent sizing recommendation (LIVE — updates instantly) */}
        {vmCount > 0 && (
          <div style={{ marginTop: 12, padding: 12, background: "#f0fdf4", borderRadius: 6, border: "1px solid #bbf7d0" }}>
            <h4 style={{ margin: "0 0 8px 0", color: "#15803d" }}>
              💡 Agent Sizing Recommendation {isDirtyFinal && <span style={{ fontSize: "0.75rem", color: "#d97706", fontWeight: 400 }}>(live preview)</span>}
            </h4>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 8, fontSize: "0.85rem" }}>
              <div><strong>Agents:</strong> {liveAgent.recommended_agent_count}</div>
              <div><strong>vCPU/agent:</strong> {liveAgent.vcpu_per_agent}</div>
              <div><strong>RAM/agent:</strong> {liveAgent.ram_gb_per_agent} GB</div>
              <div><strong>Disk/agent:</strong> {liveAgent.disk_gb_per_agent} GB</div>
            </div>
            <ul style={{ margin: "8px 0 0 0", paddingLeft: 20, fontSize: "0.8rem", color: "#6b7280" }}>
              {liveAgent.reasoning.map((r: string, i: number) => <li key={i}>{r}</li>)}
            </ul>
          </div>
        )}
      </section>

      {/* ---- Migration Schedule ---- */}
      <section style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>📅 Migration Schedule</h3>
        <p style={{ color: "#6b7280", fontSize: "0.85rem", marginTop: 0 }}>
          Define the project timeline to get schedule-aware agent recommendations. The agent sizing above
          will factor in these constraints.
        </p>
        <div style={rowStyle}>
          <div style={fieldStyle}>
            <FieldLabel text="Project Duration (days)" tip={TIPS.durationDays} />
            <input type="number" value={durationDays} onChange={e => setDurationDays(+e.target.value)} style={inputStyle} min={1} max={365} />
          </div>
          <div style={fieldStyle}>
            <FieldLabel text="Working Hours per Day" tip={TIPS.workingHours} />
            <input type="number" value={workingHours} onChange={e => setWorkingHours(+e.target.value)} style={inputStyle} min={1} max={24} step={0.5} />
          </div>
        </div>
        <div style={rowStyle}>
          <div style={fieldStyle}>
            <FieldLabel text="Working Days per Week" tip={TIPS.workingDays} />
            <select value={workingDays} onChange={e => setWorkingDays(+e.target.value)} style={inputStyle}>
              <option value={5}>5 days (weekdays only)</option>
              <option value={6}>6 days (Mon-Sat)</option>
              <option value={7}>7 days (continuous)</option>
            </select>
          </div>
          <div style={fieldStyle}>
            <FieldLabel text="Target VMs per Day (optional)" tip={TIPS.targetVmsDay} />
            <input type="number" value={targetVmsDay} onChange={e => setTargetVmsDay(+e.target.value)} style={inputStyle} min={0} />
            <span style={{ fontSize: "0.75rem", color: "#9ca3af" }}>0 = auto-calculate from duration</span>
          </div>
        </div>
        {durationDays > 0 && (
          <div style={{ marginTop: 8, padding: 12, background: "#faf5ff", borderRadius: 6, fontSize: "0.85rem", border: "1px solid #e9d5ff" }}>
            <strong>Schedule summary:</strong>{" "}
            {Math.round((durationDays / 7) * workingDays)} effective working days,{" "}
            {workingHours}h/day migration window
            {targetVmsDay > 0 && <>, targeting <strong>{targetVmsDay} VMs/day</strong></>}
          </div>
        )}
      </section>

      {/* ---- Bandwidth Model (LIVE — updates instantly) ---- */}
      <section style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>📊 Bandwidth Constraint Model {isDirtyFinal && <span style={{ fontSize: "0.75rem", color: "#d97706", fontWeight: 400 }}>(live preview — save to persist)</span>}</h3>
        <p style={{ color: "#6b7280", fontSize: "0.85rem", marginTop: 0 }}>
          These cards show the effective bandwidth at each stage of the migration pipeline.
          The lowest value is the bottleneck that limits overall throughput. Change parameters above to see the impact live.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 12 }}>
          <BwCard label="Source Host Out" value={liveBw.source_effective_mbps} unit="Mbps"
            isBottleneck={liveBw.bottleneck === "source_host_nic"} tip={TIPS.bwSourceOut} />
          {liveBw.link_effective_mbps !== null ? (
            <BwCard label="Transport Link" value={liveBw.link_effective_mbps} unit="Mbps"
              isBottleneck={liveBw.bottleneck === "transport_link"} tip={TIPS.bwTransport} />
          ) : (
            <div style={{ ...bwCardStyle, opacity: 0.5 }}>
              <div style={{ fontSize: "0.8rem", color: "#6b7280" }}>Transport Link</div>
              <div style={{ fontSize: "1.1rem", fontWeight: 600 }}>N/A (local)</div>
            </div>
          )}
          <BwCard label="Agent Ingest (total)" value={liveBw.agent_effective_mbps} unit="Mbps"
            isBottleneck={liveBw.bottleneck === "agent_ingest"} tip={TIPS.bwAgentIngest} />
          <BwCard label="PCD Storage Write" value={liveBw.storage_effective_mbps} unit="Mbps"
            isBottleneck={liveBw.bottleneck === "pcd_storage"} tip={TIPS.bwStorageWrite} />
        </div>
        <div style={{
          marginTop: 12, padding: 10, borderRadius: 6, fontSize: "0.85rem",
          background: "#fef3c7", border: "1px solid #fcd34d",
          display: "flex", alignItems: "center", gap: 8,
        }}>
          <span>⚠️ <strong>Bottleneck:</strong> {liveBw.bottleneck.replace(/_/g, " ")} ({liveBw.bottleneck_mbps.toLocaleString()} Mbps)</span>
          <Tip text={TIPS.bwBottleneck} />
        </div>

        {/* ---- Storage Transfer Feasibility ---- */}
        {feasibility && totalDiskGb > 0 && (
          <div style={{
            marginTop: 12, padding: 14, borderRadius: 6, fontSize: "0.85rem",
            background: feasibility.feasible ? "#f0fdf4" : "#fef2f2",
            border: `1px solid ${feasibility.feasible ? "#bbf7d0" : "#fecaca"}`,
          }}>
            <h4 style={{ margin: "0 0 8px 0", color: feasibility.feasible ? "#15803d" : "#dc2626" }}>
              {feasibility.feasible ? "✅" : "🚫"} Storage Transfer Feasibility
            </h4>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginBottom: 8 }}>
              <div>
                <div style={{ fontSize: "0.75rem", color: "#6b7280" }}>Total Data</div>
                <div style={{ fontWeight: 700 }}>{feasibility.totalTb.toFixed(1)} TB</div>
              </div>
              <div>
                <div style={{ fontSize: "0.75rem", color: "#6b7280" }}>Bottleneck Throughput</div>
                <div style={{ fontWeight: 700 }}>{feasibility.gbPerHour.toFixed(1)} GB/hr</div>
              </div>
              <div>
                <div style={{ fontSize: "0.75rem", color: "#6b7280" }}>Min. Transfer Time</div>
                <div style={{ fontWeight: 700 }}>{feasibility.transferDaysNeeded} working days</div>
              </div>
            </div>

            {durationDays > 0 && (
              <>
                {/* Progress bar: transfer time vs available time */}
                <div style={{ marginTop: 4, marginBottom: 4 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem", color: "#6b7280" }}>
                    <span>Transfer time vs. available window ({feasibility.effectiveDays} working days, {workingHours}h/day)</span>
                    <span>{feasibility.utilizationPct}%</span>
                  </div>
                  <div style={{ height: 8, borderRadius: 4, background: "#e5e7eb", overflow: "hidden", marginTop: 2 }}>
                    <div style={{
                      width: `${Math.min(feasibility.utilizationPct, 100)}%`,
                      height: "100%", borderRadius: 4,
                      background: feasibility.utilizationPct <= 70 ? "#22c55e" :
                                  feasibility.utilizationPct <= 100 ? "#eab308" : "#ef4444",
                    }} />
                  </div>
                </div>

                {!feasibility.feasible && (
                  <div style={{ marginTop: 8, padding: 8, borderRadius: 4, background: "#fee2e2", color: "#991b1b", fontSize: "0.8rem" }}>
                    <strong>⛔ Cannot complete in {durationDays} days.</strong>{" "}
                    Raw data transfer alone requires ~{feasibility.transferDaysNeeded} working days at the current bottleneck
                    of {feasibility.bottleneckMbps.toLocaleString()} Mbps ({feasibility.gbPerHour.toFixed(1)} GB/hr).
                    You are <strong>{feasibility.overrunDays} working days</strong> short.
                    <div style={{ marginTop: 4 }}>
                      <strong>To fix:</strong> increase project duration, extend working hours, improve the {liveBw.bottleneck.replace(/_/g, " ")} bottleneck,
                      or reduce the dataset (exclude powered-off VMs / templates).
                    </div>
                  </div>
                )}

                {feasibility.feasible && feasibility.utilizationPct > 70 && (
                  <div style={{ marginTop: 8, padding: 8, borderRadius: 4, background: "#fef9c3", color: "#854d0e", fontSize: "0.8rem" }}>
                    <strong>⚠️ Tight schedule.</strong>{" "}
                    Raw data transfer uses {feasibility.utilizationPct}% of the available window,
                    leaving little room for retries, snapshots, cutover coordination, and testing.
                    Consider extending the project duration or improving the bottleneck.
                  </div>
                )}

                {feasibility.feasible && feasibility.utilizationPct <= 70 && (
                  <div style={{ marginTop: 4, fontSize: "0.8rem", color: "#166534" }}>
                    ✅ Schedule is feasible with <strong>{100 - feasibility.utilizationPct}% headroom</strong> for retries, testing, and cutover.
                  </div>
                )}
              </>
            )}

            {durationDays <= 0 && (
              <div style={{ fontSize: "0.8rem", color: "#6b7280", marginTop: 4 }}>
                Set a project duration in the Migration Schedule section to check if this storage volume can be transferred in time.
              </div>
            )}
          </div>
        )}
      </section>

      {/* ---- Save / Re-assess Buttons ---- */}
      {isDirtyFinal && (
        <div style={{
          background: "#fffbeb", border: "1px solid #fcd34d", borderRadius: 6,
          padding: "8px 12px", marginTop: 16, fontSize: "0.85rem", color: "#92400e",
        }}>
          ⚠️ You have unsaved changes.
          {hasAssessment && " Saving will update settings but not re-score VMs — use \"Save & Re-assess\" to recalculate migration times and risk scores with the new parameters."}
        </div>
      )}

      <div style={{ display: "flex", gap: 12, marginTop: isDirtyFinal ? 8 : 16, flexWrap: "wrap", alignItems: "center" }}>
        <button onClick={handleSave} disabled={saving || reassessing} style={btnPrimary}>
          {saving ? "Saving..." : "💾 Save Settings"}
        </button>

        {hasAssessment && isDirtyFinal && (
          <button onClick={handleSaveAndReassess} disabled={saving || reassessing}
            style={{ ...btnPrimary, background: "#f59e0b" }}>
            {reassessing ? "Re-assessing..." : "🔄 Save & Re-assess"}
          </button>
        )}

        {hasAssessment && !isDirtyFinal && (
          <button onClick={handleSaveAndReassess} disabled={saving || reassessing}
            style={btnSecondary}>
            {reassessing ? "Re-assessing..." : "🔄 Re-run Assessment"}
          </button>
        )}

        {project.rvtools_filename && (
          <button onClick={() => onNavigate("analysis")} style={btnSecondary}>
            📊 Go to Analysis →
          </button>
        )}
      </div>

      {!isDirtyFinal && !hasAssessment && project.rvtools_filename && (
        <p style={{ fontSize: "0.8rem", color: "#6b7280", marginTop: 8 }}>
          💡 <strong>What-if analysis:</strong> Change any setting above (e.g. upgrade Source NIC from 10 → 25 Gbps)
          then click <strong>Save Settings</strong> to see how the bandwidth model changes.
          After running an assessment, use <strong>Save & Re-assess</strong> to recalculate all VM migration times with the new parameters.
        </p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                     */
/* ------------------------------------------------------------------ */

function Tip({ text }: { text: string }) {
  const [show, setShow] = useState(false);
  return (
    <span
      style={{ position: "relative", display: "inline-block", cursor: "help", color: "#3b82f6", fontWeight: 700, fontSize: "0.8rem" }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      ⓘ
      {show && <span style={tooltipStyle}>{text}</span>}
    </span>
  );
}

function BwCard({ label, value, unit, isBottleneck, tip }: { label: string; value: number; unit: string; isBottleneck: boolean; tip?: string }) {
  return (
    <div style={{
      ...bwCardStyle,
      borderColor: isBottleneck ? "#f59e0b" : "var(--border, #e5e7eb)",
      background: isBottleneck ? "#fffbeb" : "var(--card-bg, #f9fafb)",
    }}>
      <div style={{ fontSize: "0.8rem", color: "#6b7280" }}>
        {label} {tip && <Tip text={tip} />}
      </div>
      <div style={{ fontSize: "1.2rem", fontWeight: 700, color: isBottleneck ? "#d97706" : "inherit" }}>
        {Math.round(value).toLocaleString()} <span style={{ fontSize: "0.8rem", fontWeight: 400 }}>{unit}</span>
      </div>
      {isBottleneck && <div style={{ fontSize: "0.7rem", color: "#d97706", fontWeight: 600 }}>⚠ BOTTLENECK</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Styles                                                             */
/* ------------------------------------------------------------------ */

const sectionStyle: React.CSSProperties = {
  background: "var(--card-bg, #fff)", border: "1px solid var(--border, #e5e7eb)",
  borderRadius: 8, padding: 20, marginBottom: 16,
};

const rowStyle: React.CSSProperties = {
  display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 12,
};

const fieldStyle: React.CSSProperties = {};

const labelStyle: React.CSSProperties = {
  display: "block", marginBottom: 4, fontWeight: 600, fontSize: "0.85rem",
};

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "8px 10px", borderRadius: 6,
  border: "1px solid var(--border, #d1d5db)", fontSize: "0.9rem",
  boxSizing: "border-box",
};

const badgeStyle: React.CSSProperties = {
  padding: "2px 10px", borderRadius: 12, fontSize: "0.8rem",
  background: "var(--card-bg, #f3f4f6)", border: "1px solid var(--border, #e5e7eb)",
};

const miniCardRow: React.CSSProperties = {
  display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center",
  marginBottom: 8,
};

const bwCardStyle: React.CSSProperties = {
  padding: 12, borderRadius: 6, border: "1px solid var(--border, #e5e7eb)",
  textAlign: "center",
};

const btnPrimary: React.CSSProperties = {
  padding: "8px 18px", borderRadius: 6, border: "none",
  background: "#3b82f6", color: "#fff", cursor: "pointer", fontWeight: 600,
};

const btnSecondary: React.CSSProperties = {
  padding: "8px 18px", borderRadius: 6, border: "1px solid var(--border, #d1d5db)",
  background: "transparent", cursor: "pointer",
};

const alertError: React.CSSProperties = {
  background: "#fef2f2", color: "#dc2626", padding: "8px 12px",
  borderRadius: 6, marginBottom: 12, border: "1px solid #fecaca",
};

const alertSuccess: React.CSSProperties = {
  background: "#f0fdf4", color: "#16a34a", padding: "8px 12px",
  borderRadius: 6, marginBottom: 12, border: "1px solid #bbf7d0",
};

const tooltipStyle: React.CSSProperties = {
  position: "absolute", bottom: "calc(100% + 8px)", left: "50%",
  transform: "translateX(-50%)", width: 300, padding: "10px 12px",
  background: "#1e293b", color: "#f1f5f9", borderRadius: 6,
  fontSize: "0.8rem", lineHeight: 1.45, fontWeight: 400,
  zIndex: 50, boxShadow: "0 4px 12px rgba(0,0,0,0.25)",
  pointerEvents: "none", whiteSpace: "normal",
};
