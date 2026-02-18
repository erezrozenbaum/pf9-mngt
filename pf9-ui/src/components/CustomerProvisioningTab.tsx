import React, { useState, useEffect, useCallback, useRef } from "react";
import { API_BASE } from "../config";

/* ===================================================================
   CustomerProvisioningTab
   ===================================================================
   Wizard-style form for provisioning a complete customer environment:
   Domain → Project → User → Role → Quotas → Network → Security Group → Email

   Features:
   - Domain/Project existence check with conflict resolution
   - Project naming convention: {domain}_tenant_subid_{subscription_id}
   - Custom security group ports (ingress/egress)
   - Editable email recipients
   - Full provisioning details in welcome email
   - Provisioning job log viewer
   - Quota editor with Set Unlimited toggles
   - Physical network auto-discovery from OpenStack
*/

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface ComputeQuotas {
  cores: number;
  ram: number;       // stored as GiB in the UI, converted to MB for API
  instances: number;
  server_groups: number;
  server_group_members: number;
}

interface NetworkQuotas {
  network: number;
  subnet: number;
  router: number;
  port: number;
  floatingip: number;
  security_group: number;
  security_group_rule: number;
}

interface StorageQuotas {
  gigabytes: number;
  volumes: number;
  snapshots: number;
  per_volume_gigabytes: number;
}

interface CustomSgRule {
  direction: "ingress" | "egress";
  protocol: string;
  port_range_min: number | null;
  port_range_max: number | null;
  remote_ip_prefix: string;
  description: string;
}

interface ProvisionForm {
  domain_name: string;
  domain_description: string;
  existing_domain_id: string;
  project_name: string;
  project_description: string;
  subscription_id: string;
  username: string;
  user_email: string;
  user_password: string;
  user_role: string;
  create_network: boolean;
  network_name: string;
  network_type: "vlan" | "flat" | "vxlan";
  physical_network: string;
  vlan_id: string;
  subnet_cidr: string;
  gateway_ip: string;
  dns_nameservers: string;
  enable_dhcp: boolean;
  allocation_pool_start: string;
  allocation_pool_end: string;
  create_security_group: boolean;
  security_group_name: string;
  custom_sg_rules: CustomSgRule[];
  send_welcome_email: boolean;
  include_user_email: boolean;
  email_recipients: string;
  compute_quotas: ComputeQuotas;
  network_quotas: NetworkQuotas;
  storage_quotas: StorageQuotas;
}

interface DomainCheckResult {
  exists: boolean;
  domain: {
    id: string;
    name: string;
    description: string;
    enabled: boolean;
    projects: number;
    users: number;
  } | null;
}

interface ProjectCheckResult {
  exists: boolean;
  project: {
    id: string;
    name: string;
    description: string;
    domain_id: string;
    enabled: boolean;
  } | null;
}

interface ProvisioningJob {
  job_id: string;
  domain_name: string;
  project_name: string;
  username: string;
  user_email: string;
  user_role: string;
  status: string;
  created_by: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
}

interface ProvisioningStep {
  step_number: number;
  step_name: string;
  description: string;
  status: string;
  resource_id: string | null;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
}

type QuotaSubTab = "compute" | "storage" | "network";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const DEFAULT_COMPUTE_QUOTAS: ComputeQuotas = {
  cores: 20, ram: 50, instances: 10,
  server_groups: 10, server_group_members: 10,
};

const DEFAULT_NETWORK_QUOTAS: NetworkQuotas = {
  network: 100, subnet: 100, router: 10, port: 500,
  floatingip: 50, security_group: 10, security_group_rule: 100,
};

const DEFAULT_STORAGE_QUOTAS: StorageQuotas = {
  gigabytes: 300, volumes: 10, snapshots: 10, per_volume_gigabytes: -1,
};

const QUOTA_LABELS: Record<string, string> = {
  cores: "Cores", ram: "RAM", instances: "VMs",
  server_groups: "Server Groups", server_group_members: "Server Groups Members",
  network: "Networks", subnet: "Subnets", router: "Routers", port: "Ports",
  floatingip: "Public IPs", security_group: "Security Groups",
  security_group_rule: "Security Group Rules",
  gigabytes: "Total Block Storage (GB)", volumes: "Volumes",
  snapshots: "Volume Snapshots", per_volume_gigabytes: "Max Volume Size (GB)",
};

const QUOTA_HINTS: Record<string, string> = {
  server_groups: "A server group defines a set of VMs that follow anti-affinity or affinity policies for scheduling on hosts.",
  server_group_members: "Maximum number of VMs that can be part of a single server group.",
};

const DEFAULT_SG_RULES_DISPLAY = [
  { direction: "Ingress", protocol: "TCP", port: "22", desc: "SSH" },
  { direction: "Ingress", protocol: "ICMP", port: "All", desc: "ICMP Ping" },
  { direction: "Ingress", protocol: "TCP", port: "443", desc: "HTTPS" },
  { direction: "Ingress", protocol: "TCP", port: "80", desc: "HTTP" },
  { direction: "Egress", protocol: "All", port: "All", desc: "Allow all egress" },
];

const COMMON_PORT_PRESETS = [
  { label: "RDP (3389)", port: 3389, protocol: "tcp", desc: "Remote Desktop (Windows)" },
  { label: "WinRM (5985-5986)", port_min: 5985, port_max: 5986, protocol: "tcp", desc: "Windows Remote Management" },
  { label: "MySQL (3306)", port: 3306, protocol: "tcp", desc: "MySQL Database" },
  { label: "PostgreSQL (5432)", port: 5432, protocol: "tcp", desc: "PostgreSQL Database" },
  { label: "DNS (53)", port: 53, protocol: "udp", desc: "DNS" },
  { label: "SMTP (25)", port: 25, protocol: "tcp", desc: "SMTP Mail" },
];

const INIT_FORM: ProvisionForm = {
  domain_name: "", domain_description: "", existing_domain_id: "",
  project_name: "", project_description: "", subscription_id: "",
  username: "", user_email: "", user_password: "", user_role: "member",
  create_network: true, network_name: "", network_type: "vlan",
  physical_network: "", vlan_id: "", subnet_cidr: "10.0.0.0/24",
  gateway_ip: "", dns_nameservers: "8.8.8.8, 8.8.4.4",
  enable_dhcp: true, allocation_pool_start: "", allocation_pool_end: "",
  create_security_group: true, security_group_name: "default-sg",
  custom_sg_rules: [], send_welcome_email: true, include_user_email: false, email_recipients: "",
  compute_quotas: { ...DEFAULT_COMPUTE_QUOTAS },
  network_quotas: { ...DEFAULT_NETWORK_QUOTAS },
  storage_quotas: { ...DEFAULT_STORAGE_QUOTAS },
};

const WIZARD_STEPS = [
  "Domain & Project", "User & Role", "Quotas",
  "Network & Security", "Review & Provision",
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("auth_token");
  return token
    ? { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }
    : { "Content-Type": "application/json" };
}

function statusBadge(status: string) {
  const colors: Record<string, string> = {
    completed: "#48bb78", running: "#4299e1", pending: "#a0aec0",
    failed: "#fc8181", partial: "#ed8936",
  };
  return (
    <span style={{
      background: colors[status] || "#a0aec0", color: "white",
      padding: "2px 10px", borderRadius: 12, fontSize: 12,
      fontWeight: 600, textTransform: "uppercase" as const,
    }}>
      {status}
    </span>
  );
}

function fmtDate(d: string | null): string {
  if (!d) return "\u2014";
  return new Date(d).toLocaleString();
}

// ---------------------------------------------------------------------------
// QuotaFieldItem — individual quota field with Set Unlimited toggle
// ---------------------------------------------------------------------------
const qfInputStyle: React.CSSProperties = {
  padding: "8px 12px", borderRadius: 6,
  border: "1px solid var(--pf9-border)",
  background: "var(--pf9-bg-input)",
  color: "var(--pf9-text)", fontSize: 14,
};

interface QuotaFieldItemProps {
  fieldKey: string;
  value: number;
  isUnlimited: boolean;
  hint?: string;
  isRam?: boolean;
  onChangeValue: (v: number) => void;
  onToggleUnlimited: () => void;
}

const QuotaFieldItem: React.FC<QuotaFieldItemProps> = ({
  fieldKey, value, isUnlimited, hint, isRam, onChangeValue, onToggleUnlimited,
}) => {
  const [showHint, setShowHint] = useState(false);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--pf9-text)" }}>
          {QUOTA_LABELS[fieldKey] || fieldKey} *
        </span>
        {hint && (
          <span
            style={{ fontSize: 12, color: "var(--pf9-text-muted)", cursor: "help", position: "relative" }}
            onMouseEnter={() => setShowHint(true)}
            onMouseLeave={() => setShowHint(false)}
          >
            ⓘ <span style={{ color: "var(--pf9-toggle-active)", fontSize: 11 }}>Hint</span>
            {showHint && (
              <div style={{
                position: "absolute", bottom: "100%", left: 0, width: 280, padding: 10, borderRadius: 6,
                background: "var(--pf9-tooltip-bg)", color: "white", fontSize: 11, lineHeight: 1.5, zIndex: 100,
                boxShadow: "0 4px 12px rgba(0,0,0,0.3)", marginBottom: 4,
              }}>
                {hint}
              </div>
            )}
          </span>
        )}
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input
          type="number"
          value={isUnlimited ? -1 : value}
          disabled={isUnlimited}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => onChangeValue(parseInt(e.target.value) || 0)}
          style={{
            ...qfInputStyle, flex: 1,
            opacity: isUnlimited ? 0.5 : 1,
            background: isUnlimited ? "var(--pf9-bg-muted)" : "var(--pf9-bg-input)",
          }}
        />
        {isRam && (
          <span style={{
            padding: "8px 12px", borderRadius: 6,
            border: "1px solid var(--pf9-border)",
            background: "var(--pf9-bg-card)",
            fontSize: 13, color: "var(--pf9-text-secondary)", fontWeight: 500,
            whiteSpace: "nowrap",
          }}>
            GiB
          </span>
        )}
      </div>
      <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", marginTop: 2 }}>
        <div
          onClick={onToggleUnlimited}
          style={{
            width: 36, height: 20, borderRadius: 10, position: "relative", cursor: "pointer",
            background: isUnlimited ? "var(--pf9-toggle-active)" : "var(--pf9-toggle-inactive)", transition: "background 0.2s",
          }}
        >
          <div style={{
            width: 16, height: 16, borderRadius: "50%", background: "white",
            position: "absolute", top: 2,
            left: isUnlimited ? 18 : 2,
            transition: "left 0.2s",
            boxShadow: "0 1px 3px rgba(0,0,0,0.2)",
          }} />
        </div>
        <span style={{ fontSize: 12, color: "var(--pf9-text-secondary)" }}>Set Unlimited</span>
      </label>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
interface Props { isAdmin: boolean; }

const CustomerProvisioningTab: React.FC<Props> = ({ isAdmin }) => {
  void isAdmin; // reserved for future use
  const [activeView, setActiveView] = useState<"wizard" | "logs">("wizard");
  const [wizardStep, setWizardStep] = useState(0);
  const [form, setForm] = useState<ProvisionForm>({ ...INIT_FORM });
  const [provisioning, setProvisioning] = useState(false);
  const [provisionResult, setProvisionResult] = useState<any>(null);

  // Domain / Project existence checks
  const [domainCheck, setDomainCheck] = useState<DomainCheckResult | null>(null);
  const [domainChecking, setDomainChecking] = useState(false);
  const [domainAction, setDomainAction] = useState<"create_new" | "use_existing" | null>(null);
  const [projectCheck, setProjectCheck] = useState<ProjectCheckResult | null>(null);
  const [projectChecking, setProjectChecking] = useState(false);

  // New custom rule form
  const [newRule, setNewRule] = useState<CustomSgRule>({
    direction: "ingress", protocol: "tcp",
    port_range_min: null, port_range_max: null,
    remote_ip_prefix: "0.0.0.0/0", description: "",
  });

  // Logs
  const [jobs, setJobs] = useState<ProvisioningJob[]>([]);
  const [jobsTotal, setJobsTotal] = useState(0);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [selectedJob, setSelectedJob] = useState<string | null>(null);
  const [jobSteps, setJobSteps] = useState<ProvisioningStep[]>([]);
  const [jobDetail, setJobDetail] = useState<any>(null);

  // Quota sub-tab
  const [quotaTab, setQuotaTab] = useState<QuotaSubTab>("compute");

  // Physical networks
  const [physicalNetworks, setPhysicalNetworks] = useState<string[]>([]);
  const [physNetsLoading, setPhysNetsLoading] = useState(false);

  // Keystone roles
  const [keystoneRoles, setKeystoneRoles] = useState<{ id: string; name: string; label?: string }[]>([]);

  const domainCheckTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const projectCheckTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Fetch physical networks ──
  const fetchPhysicalNetworks = useCallback(async () => {
    setPhysNetsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/provisioning/physical-networks`, { headers: authHeaders() });
      if (res.ok) {
        const data = await res.json();
        const nets: string[] = data.physical_networks || ["physnet1"];
        setPhysicalNetworks(nets);
        // Auto-select first if form has no value
        setForm((p: ProvisionForm) => {
          if (!p.physical_network && nets.length > 0) return { ...p, physical_network: nets[0] };
          return p;
        });
      }
    } catch (e) {
      console.error("Failed to fetch physical networks:", e);
      setPhysicalNetworks(["physnet1"]);
    } finally {
      setPhysNetsLoading(false);
    }
  }, []);

  // ── Fetch available Keystone roles ──
  const fetchRoles = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/provisioning/roles`, { headers: authHeaders() });
      if (res.ok) {
        const data = await res.json();
        const roles = data.roles || [];
        setKeystoneRoles(roles);
        // Auto-select first role if current form value isn't in the list
        if (roles.length > 0) {
          setForm((p: ProvisionForm) => {
            const valid = roles.some((r: { name: string }) => r.name === p.user_role);
            return valid ? p : { ...p, user_role: roles[0].name };
          });
        }
      }
    } catch (e) {
      console.error("Failed to fetch roles:", e);
      // Fallback to default set if API fails
      setKeystoneRoles([{ id: "1", name: "member", label: "Self-service User" }, { id: "2", name: "admin", label: "Administrator" }, { id: "3", name: "reader", label: "Read Only User" }]);
    }
  }, []);

  // ── Check domain existence (debounced) ──
  const checkDomain = useCallback(async (name: string) => {
    if (!name || name.length < 2) { setDomainCheck(null); setDomainAction(null); return; }
    setDomainChecking(true);
    try {
      const res = await fetch(
        `${API_BASE}/api/provisioning/check-domain/${encodeURIComponent(name)}`,
        { headers: authHeaders() },
      );
      if (res.ok) {
        const data: DomainCheckResult = await res.json();
        setDomainCheck(data);
        if (!data.exists) setDomainAction("create_new");
        else setDomainAction(null);
      }
    } catch (e) { console.error("Domain check failed:", e); }
    finally { setDomainChecking(false); }
  }, []);

  // ── Check project existence (debounced) ──
  const checkProject = useCallback(async (name: string, domainId?: string) => {
    if (!name || name.length < 2) { setProjectCheck(null); return; }
    setProjectChecking(true);
    try {
      const qs = domainId ? `?domain_id=${domainId}` : "";
      const res = await fetch(
        `${API_BASE}/api/provisioning/check-project/${encodeURIComponent(name)}${qs}`,
        { headers: authHeaders() },
      );
      if (res.ok) setProjectCheck(await res.json());
    } catch (e) { console.error("Project check failed:", e); }
    finally { setProjectChecking(false); }
  }, []);

  // ── Fetch logs ──
  const fetchLogs = useCallback(async () => {
    setJobsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/provisioning/logs?limit=50`, { headers: authHeaders() });
      if (res.ok) { const d = await res.json(); setJobs(d.jobs || []); setJobsTotal(d.total || 0); }
    } catch (e) { console.error("Failed to fetch provisioning logs:", e); }
    finally { setJobsLoading(false); }
  }, []);

  const fetchJobDetail = useCallback(async (jobId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/provisioning/logs/${jobId}`, { headers: authHeaders() });
      if (res.ok) { const d = await res.json(); setJobSteps(d.steps || []); setJobDetail(d.job); }
    } catch (e) { console.error("Failed to fetch job detail:", e); }
  }, []);

  useEffect(() => { fetchLogs(); fetchPhysicalNetworks(); fetchRoles(); }, [fetchLogs, fetchPhysicalNetworks, fetchRoles]);
  useEffect(() => { if (selectedJob) fetchJobDetail(selectedJob); }, [selectedJob, fetchJobDetail]);

  // ── Domain name change with debounced check ──
  const handleDomainNameChange = (value: string) => {
    const base: Partial<ProvisionForm> = { domain_name: value, existing_domain_id: "" };
    if (value && form.subscription_id) base.project_name = `${value}_tenant_subid_${form.subscription_id}`;
    setForm((p: ProvisionForm) => ({ ...p, ...base }));
    setDomainCheck(null); setDomainAction(null);
    if (domainCheckTimer.current) clearTimeout(domainCheckTimer.current);
    domainCheckTimer.current = setTimeout(() => checkDomain(value), 600);
  };

  // ── Subscription ID change → auto-update project name ──
  const handleSubscriptionIdChange = (value: string) => {
    const proj = form.domain_name ? `${form.domain_name}_tenant_subid_${value}` : "";
    setForm((p: ProvisionForm) => ({ ...p, subscription_id: value, project_name: proj }));
    if (proj) {
      if (projectCheckTimer.current) clearTimeout(projectCheckTimer.current);
      projectCheckTimer.current = setTimeout(() => checkProject(proj, form.existing_domain_id || undefined), 600);
    }
  };

  const handleUseExistingDomain = () => {
    if (domainCheck?.domain) {
      setForm((p: ProvisionForm) => ({ ...p, existing_domain_id: domainCheck.domain!.id }));
      setDomainAction("use_existing");
    }
  };
  const handleCreateNewDomain = () => {
    setForm((p: ProvisionForm) => ({ ...p, existing_domain_id: "" }));
    setDomainCheck(null); setDomainAction("create_new");
  };

  const updateForm = (field: keyof ProvisionForm, value: any) =>
    setForm((p: ProvisionForm) => ({ ...p, [field]: value }));

  const updateQuota = (cat: "compute_quotas" | "network_quotas" | "storage_quotas", field: string, value: number) =>
    setForm((p: ProvisionForm) => ({ ...p, [cat]: { ...(p[cat] as any), [field]: value } }));

  // ── Custom SG rules ──
  const addCustomRule = () => {
    if (!newRule.protocol || (newRule.protocol !== "icmp" && !newRule.port_range_min)) return;
    setForm((p: ProvisionForm) => ({ ...p, custom_sg_rules: [...p.custom_sg_rules, { ...newRule }] }));
    setNewRule({ direction: "ingress", protocol: "tcp", port_range_min: null, port_range_max: null, remote_ip_prefix: "0.0.0.0/0", description: "" });
  };
  const addPresetRule = (preset: (typeof COMMON_PORT_PRESETS)[number]) => {
    const rule: CustomSgRule = {
      direction: "ingress", protocol: preset.protocol,
      port_range_min: "port_min" in preset ? (preset as any).port_min : preset.port,
      port_range_max: "port_max" in preset ? (preset as any).port_max : preset.port,
      remote_ip_prefix: "0.0.0.0/0", description: preset.desc,
    };
    setForm((p: ProvisionForm) => ({ ...p, custom_sg_rules: [...p.custom_sg_rules, rule] }));
  };
  const removeCustomRule = (idx: number) =>
    setForm((p: ProvisionForm) => ({ ...p, custom_sg_rules: p.custom_sg_rules.filter((_: CustomSgRule, i: number) => i !== idx) }));

  // ── Provision ──
  const handleProvision = async () => {
    setProvisioning(true); setProvisionResult(null);
    try {
      const extraRecipients = form.email_recipients.split(",").map((s: string) => s.trim()).filter(Boolean);
      const payload = {
        ...form,
        existing_domain_id: form.existing_domain_id || null,
        vlan_id: form.vlan_id ? parseInt(form.vlan_id) : null,
        dns_nameservers: form.dns_nameservers.split(",").map((s: string) => s.trim()).filter(Boolean),
        include_user_email: form.include_user_email,
        email_recipients: extraRecipients,
        // Convert RAM from GiB (UI) to MB (API)
        compute_quotas: { ...form.compute_quotas, ram: form.compute_quotas.ram * 1024 },
      };
      const res = await fetch(`${API_BASE}/api/provisioning/provision`, {
        method: "POST", headers: authHeaders(), body: JSON.stringify(payload),
      });
      const data = await res.json();
      setProvisionResult(data);
      if (data.status === "completed") fetchLogs();
    } catch (e: any) {
      setProvisionResult({ status: "failed", error: e.message });
    } finally { setProvisioning(false); }
  };

  const resetWizard = () => {
    setForm({ ...INIT_FORM, physical_network: physicalNetworks[0] || "" }); setWizardStep(0); setProvisionResult(null);
    setDomainCheck(null); setDomainAction(null); setProjectCheck(null); setQuotaTab("compute");
  };

  // ── Quota field renderer with Set Unlimited toggle ──
  const renderQuotaField = (
    cat: "compute_quotas" | "network_quotas" | "storage_quotas",
    key: string,
    val: number,
    defaultVal: number,
  ) => {
    const isUnlimited = val === -1;
    const hint = QUOTA_HINTS[key];
    const isRam = key === "ram";
    return (
      <QuotaFieldItem
        key={key}
        fieldKey={key}
        value={val}
        isUnlimited={isUnlimited}
        hint={hint}
        isRam={isRam}
        onChangeValue={(v: number) => updateQuota(cat, key, v)}
        onToggleUnlimited={() => {
          if (isUnlimited) updateQuota(cat, key, defaultVal);
          else updateQuota(cat, key, -1);
        }}
      />
    );
  };

  // ── Wizard step content ──
  const renderStepContent = () => {
    switch (wizardStep) {
      // ── Step 0: Domain & Project ──
      case 0:
        return (
          <div style={{ display: "grid", gap: 16 }}>
            <h3 style={{ margin: 0, color: "var(--pf9-heading)" }}>🏢 Domain & Project</h3>
            <p style={{ margin: 0, fontSize: 13, color: "var(--pf9-text-secondary)" }}>
              A domain is the top-level organizational unit. A project is created inside
              the domain for resource isolation. The project name follows a naming convention.
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              {/* Domain Name with existence check */}
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>Domain Name *</span>
                <input value={form.domain_name}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => handleDomainNameChange(e.target.value)}
                  placeholder="e.g. acme-corp"
                  style={{ ...inputStyle,
                    borderColor: domainCheck?.exists && !domainAction ? "var(--pf9-warning-border)"
                      : domainCheck && !domainCheck.exists ? "var(--pf9-success)" : undefined }}
                />
                {domainChecking && <span style={{ fontSize: 11, color: "var(--pf9-text-muted)" }}>⏳ Checking...</span>}

                {/* Domain exists warning */}
                {domainCheck?.exists && !domainAction && (
                  <div style={{ background: "var(--pf9-warning-bg)", border: "1px solid var(--pf9-warning-border)", borderRadius: 6, padding: 12, fontSize: 12, marginTop: 4 }}>
                    <div style={{ fontWeight: 700, color: "var(--pf9-warning-text)", marginBottom: 6 }}>
                      ⚠️ Domain "{domainCheck.domain?.name}" already exists
                    </div>
                    <div style={{ color: "var(--pf9-text-secondary)", marginBottom: 8 }}>
                      This domain has {domainCheck.domain?.projects || 0} project(s) and {domainCheck.domain?.users || 0} user(s).
                    </div>
                    <div style={{ display: "flex", gap: 8 }}>
                      <button onClick={handleUseExistingDomain}
                        style={{ ...btnStyleSm, background: "var(--pf9-toggle-active)" }}>Use Existing</button>
                      <button onClick={handleCreateNewDomain}
                        style={{ ...btnStyleSm, background: "var(--pf9-text-secondary)" }}>Create Different</button>
                    </div>
                  </div>
                )}
                {domainCheck?.exists && domainAction === "use_existing" && (
                  <div style={{ background: "var(--pf9-info-bg)", border: "1px solid var(--pf9-info-border)", borderRadius: 6, padding: 8, fontSize: 12, color: "var(--pf9-info-text)" }}>
                    ✅ Using existing domain: <strong>{domainCheck.domain?.name}</strong> ({domainCheck.domain?.id?.substring(0, 8)}...)
                  </div>
                )}
                {domainCheck && !domainCheck.exists && (
                  <span style={{ fontSize: 11, color: "var(--pf9-success)" }}>✅ Domain name is available</span>
                )}
              </div>

              {/* Description */}
              <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>Description</span>
                <input value={form.domain_description}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => updateForm("domain_description", e.target.value)}
                  placeholder="Customer description" style={inputStyle} />
              </label>
            </div>

            {/* Subscription ID & auto-generated Project Name */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 8 }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>Subscription ID *</span>
                <input value={form.subscription_id}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => handleSubscriptionIdChange(e.target.value)}
                  placeholder="e.g. 001" style={inputStyle} />
                <span style={{ fontSize: 11, color: "var(--pf9-text-muted)" }}>Used in project naming convention</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>Project Name * <span style={{ fontWeight: 400, color: "var(--pf9-text-muted)" }}>(auto-generated)</span></span>
                <input value={form.project_name} readOnly
                  style={{ ...inputStyle, background: "var(--pf9-bg-muted)", cursor: "default" }} />
                {projectChecking && <span style={{ fontSize: 11, color: "var(--pf9-text-muted)" }}>⏳ Checking...</span>}
                {projectCheck?.exists && (
                  <span style={{ fontSize: 11, color: "var(--pf9-danger-text)" }}>
                    ⚠️ This project already exists in domain {projectCheck.project?.domain_id?.substring(0, 8)}...
                  </span>
                )}
                {projectCheck && !projectCheck.exists && (
                  <span style={{ fontSize: 11, color: "var(--pf9-success)" }}>✅ Project name is available</span>
                )}
              </div>
            </div>

            {/* Project Description */}
            <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span style={{ fontWeight: 600, fontSize: 13 }}>Project Description</span>
              <input value={form.project_description}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => updateForm("project_description", e.target.value)}
                placeholder="Optional project description" style={inputStyle} />
            </label>
          </div>
        );

      // ── Step 1: User & Role ──
      case 1:
        return (
          <div style={{ display: "grid", gap: 16 }}>
            <h3 style={{ margin: 0, color: "var(--pf9-heading)" }}>👤 User & Role</h3>
            <p style={{ margin: 0, fontSize: 13, color: "var(--pf9-text-secondary)" }}>
              Create the initial user inside the new domain.
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>Username *</span>
                <input value={form.username}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => updateForm("username", e.target.value)}
                  placeholder="e.g. john.doe" style={inputStyle} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>Email</span>
                <input type="email" value={form.user_email}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                    const val = e.target.value;
                    setForm((p: ProvisionForm) => ({
                      ...p,
                      user_email: val,
                      // Auto-enable include_user_email when a valid email is entered
                      include_user_email: val.includes("@") ? true : p.include_user_email,
                    }));
                  }}
                  placeholder="user@example.com" style={inputStyle} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>Password <span style={{ fontWeight: 400, color: "var(--pf9-text-muted)" }}>(blank = auto-generate)</span></span>
                <input type="password" value={form.user_password}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => updateForm("user_password", e.target.value)}
                  placeholder="Leave empty to auto-generate" style={inputStyle} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>Role</span>
                <select value={form.user_role}
                  onChange={(e: React.ChangeEvent<HTMLSelectElement>) => updateForm("user_role", e.target.value)}
                  style={inputStyle}>
                  {keystoneRoles.length > 0 ? keystoneRoles.map(r => (
                    <option key={r.id} value={r.name}>{r.label || r.name.charAt(0).toUpperCase() + r.name.slice(1)}</option>
                  )) : (
                    <>
                      <option value="member">Self-service User</option>
                      <option value="admin">Administrator</option>
                      <option value="reader">Read Only User</option>
                    </>
                  )}
                </select>
              </label>
            </div>

            {/* Welcome Email section */}
            <div style={{ background: "var(--pf9-bg-card)", borderRadius: 8, padding: 16, border: "1px solid var(--pf9-border)", marginTop: 8 }}>
              <label style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, cursor: "pointer" }}>
                <input type="checkbox" checked={form.send_welcome_email}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => updateForm("send_welcome_email", e.target.checked)} />
                <span style={{ fontWeight: 600, fontSize: 14 }}>📧 Send Welcome Email</span>
              </label>
              {form.send_welcome_email && (
                <div style={{ display: "grid", gap: 12 }}>
                  {/* Opt-in for created user email */}
                  {form.user_email && (
                    <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                      <input type="checkbox" checked={form.include_user_email}
                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => updateForm("include_user_email", e.target.checked)} />
                      <span style={{ fontSize: 13, color: "var(--pf9-text-secondary)" }}>
                        Include created user email (<strong>{form.user_email}</strong>) as recipient
                      </span>
                    </label>
                  )}
                  {/* Manual email recipients */}
                  <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <span style={{ fontSize: 13, fontWeight: 500 }}>Email Recipients <span style={{ fontWeight: 400, color: "var(--pf9-text-muted)" }}>(comma-separated)</span></span>
                    <input value={form.email_recipients}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => updateForm("email_recipients", e.target.value)}
                      placeholder="admin@example.com, noc@example.com" style={inputStyle} />
                  </label>
                  <div style={{ fontSize: 12, color: "var(--pf9-text-secondary)" }}>
                    {(() => {
                      const recipients: string[] = [];
                      if (form.include_user_email && form.user_email) recipients.push(form.user_email);
                      form.email_recipients.split(",").map((s: string) => s.trim()).filter(Boolean).forEach((r: string) => recipients.push(r));
                      if (recipients.length === 0) return <span style={{ color: "var(--pf9-danger-text)" }}>⚠️ No recipients set. Add recipients above.</span>;
                      return <span>📧 Will send to: <strong>{recipients.join(", ")}</strong></span>;
                    })()}
                  </div>
                </div>
              )}
            </div>
          </div>
        );

      // ── Step 2: Quotas (tabbed: Compute | Block Storage | Network) ──
      case 2: {
        const computeDefaults: Record<string, number> = { cores: 20, ram: 50, instances: 10, server_groups: 10, server_group_members: 10 };
        const storageDefaults: Record<string, number> = { gigabytes: 300, volumes: 10, snapshots: 10, per_volume_gigabytes: -1 };
        const networkDefaults: Record<string, number> = { network: 100, subnet: 100, router: 10, port: 500, floatingip: 50, security_group: 10, security_group_rule: 100 };
        return (
          <div style={{ display: "grid", gap: 16 }}>
            <h3 style={{ margin: 0, color: "var(--pf9-heading)" }}>📊 Edit Quotas for Tenant {form.domain_name || "..."}</h3>

            {/* Quota sub-tabs */}
            <div style={{ display: "flex", gap: 0, borderBottom: "2px solid var(--pf9-border)" }}>
              {(["compute", "storage", "network"] as QuotaSubTab[]).map((tab) => {
                const labels: Record<QuotaSubTab, string> = { compute: "Compute Quotas", storage: "Block Storage Quotas", network: "Network Quotas" };
                return (
                  <button key={tab} onClick={() => setQuotaTab(tab)}
                    style={{
                      padding: "10px 20px", border: "none", cursor: "pointer", fontSize: 14, fontWeight: quotaTab === tab ? 700 : 400,
                      background: "transparent", color: quotaTab === tab ? "var(--pf9-accent-orange)" : "var(--pf9-text-secondary)",
                      borderBottom: quotaTab === tab ? "3px solid var(--pf9-accent-orange)" : "3px solid transparent",
                      marginBottom: -2,
                    }}>
                    {labels[tab]}
                  </button>
                );
              })}
            </div>

            {/* Compute Quotas */}
            {quotaTab === "compute" && (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, padding: "8px 0" }}>
                {Object.entries(form.compute_quotas).map(([key, val]) =>
                  renderQuotaField("compute_quotas", key, val, computeDefaults[key] ?? 10)
                )}
              </div>
            )}

            {/* Block Storage Quotas */}
            {quotaTab === "storage" && (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, padding: "8px 0" }}>
                {Object.entries(form.storage_quotas).map(([key, val]) =>
                  renderQuotaField("storage_quotas", key, val, storageDefaults[key] ?? 10)
                )}
              </div>
            )}

            {/* Network Quotas */}
            {quotaTab === "network" && (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, padding: "8px 0" }}>
                {Object.entries(form.network_quotas).map(([key, val]) =>
                  renderQuotaField("network_quotas", key, val, networkDefaults[key] ?? 10)
                )}
              </div>
            )}
          </div>
        );
      }

      // ── Step 3: Network & Security ──
      case 3:
        return (
          <div style={{ display: "grid", gap: 16 }}>
            <h3 style={{ margin: 0, color: "var(--pf9-heading)" }}>🔒 Network & Security Group</h3>

            {/* External Network */}
            <div style={{ background: "var(--pf9-bg-card)", borderRadius: 8, padding: 16, border: "1px solid var(--pf9-border)" }}>
              <label style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, cursor: "pointer" }}>
                <input type="checkbox" checked={form.create_network}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => updateForm("create_network", e.target.checked)} />
                <span style={{ fontWeight: 600, fontSize: 14 }}>Create External Network</span>
              </label>
              {form.create_network && (
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <span style={{ fontSize: 13, fontWeight: 500 }}>Network Name</span>
                    <input value={form.network_name}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => updateForm("network_name", e.target.value)}
                      placeholder={`${form.domain_name || "customer"}-ext-net`} style={inputStyle} />
                  </label>
                  <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <span style={{ fontSize: 13, fontWeight: 500 }}>Network Type</span>
                    <select value={form.network_type}
                      onChange={(e: React.ChangeEvent<HTMLSelectElement>) => updateForm("network_type", e.target.value)}
                      style={inputStyle}>
                      <option value="vlan">VLAN</option>
                      <option value="flat">Flat</option>
                      <option value="vxlan">VXLAN</option>
                    </select>
                  </label>
                  <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <span style={{ fontSize: 13, fontWeight: 500 }}>Physical Network</span>
                    {physNetsLoading ? (
                      <div style={{ ...inputStyle, color: "var(--pf9-text-muted)" }}>Loading...</div>
                    ) : (
                      <select
                        value={form.physical_network}
                        onChange={(e: React.ChangeEvent<HTMLSelectElement>) => updateForm("physical_network", e.target.value)}
                        style={inputStyle}
                      >
                        {physicalNetworks.map((pn) => (
                          <option key={pn} value={pn}>{pn}</option>
                        ))}
                      </select>
                    )}
                    <span style={{ fontSize: 11, color: "var(--pf9-text-muted)" }}>
                      {physicalNetworks.length <= 1 ? "System default physical network" : `${physicalNetworks.length} physical networks available`}
                    </span>
                  </label>
                  <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <span style={{ fontSize: 13, fontWeight: 500 }}>VLAN ID <span style={{ fontWeight: 400, color: "var(--pf9-text-muted)" }}>(optional)</span></span>
                    <input type="number" value={form.vlan_id}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => updateForm("vlan_id", e.target.value)}
                      placeholder="e.g. 100" style={inputStyle} />
                  </label>
                  <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <span style={{ fontSize: 13, fontWeight: 500 }}>Subnet CIDR</span>
                    <input value={form.subnet_cidr}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => updateForm("subnet_cidr", e.target.value)}
                      placeholder="10.0.0.0/24" style={inputStyle} />
                  </label>
                  <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <span style={{ fontSize: 13, fontWeight: 500 }}>Gateway IP <span style={{ fontWeight: 400, color: "var(--pf9-text-muted)" }}>(optional)</span></span>
                    <input value={form.gateway_ip}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => updateForm("gateway_ip", e.target.value)}
                      placeholder="e.g. 10.0.0.1" style={inputStyle} />
                  </label>
                  <label style={{ display: "flex", flexDirection: "column", gap: 4, gridColumn: "span 2" }}>
                    <span style={{ fontSize: 13, fontWeight: 500 }}>DNS Nameservers <span style={{ fontWeight: 400, color: "var(--pf9-text-muted)" }}>(comma-separated)</span></span>
                    <input value={form.dns_nameservers}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => updateForm("dns_nameservers", e.target.value)}
                      placeholder="8.8.8.8, 8.8.4.4" style={inputStyle} />
                  </label>

                  {/* DHCP Toggle */}
                  <label style={{ display: "flex", alignItems: "center", gap: 8, gridColumn: "span 2", cursor: "pointer", marginTop: 4 }}>
                    <input type="checkbox" checked={form.enable_dhcp}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => updateForm("enable_dhcp", e.target.checked)} />
                    <span style={{ fontWeight: 600, fontSize: 13 }}>Enable DHCP</span>
                    <span style={{ fontSize: 11, color: "var(--pf9-text-muted)" }}>(allocates IPs automatically to instances on this subnet)</span>
                  </label>

                  {/* Allocation Pool (shown when DHCP is enabled) */}
                  {form.enable_dhcp && (
                    <>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ fontSize: 13, fontWeight: 500 }}>Allocation Pool Start <span style={{ fontWeight: 400, color: "var(--pf9-text-muted)" }}>(optional)</span></span>
                        <input value={form.allocation_pool_start}
                          onChange={(e: React.ChangeEvent<HTMLInputElement>) => updateForm("allocation_pool_start", e.target.value)}
                          placeholder="e.g. 10.0.0.10" style={inputStyle} />
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ fontSize: 13, fontWeight: 500 }}>Allocation Pool End <span style={{ fontWeight: 400, color: "var(--pf9-text-muted)" }}>(optional)</span></span>
                        <input value={form.allocation_pool_end}
                          onChange={(e: React.ChangeEvent<HTMLInputElement>) => updateForm("allocation_pool_end", e.target.value)}
                          placeholder="e.g. 10.0.0.254" style={inputStyle} />
                      </label>
                    </>
                  )}
                </div>
              )}
            </div>

            {/* Security Group */}
            <div style={{ background: "var(--pf9-bg-card)", borderRadius: 8, padding: 16, border: "1px solid var(--pf9-border)" }}>
              <label style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, cursor: "pointer" }}>
                <input type="checkbox" checked={form.create_security_group}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => updateForm("create_security_group", e.target.checked)} />
                <span style={{ fontWeight: 600, fontSize: 14 }}>Create Default Security Group</span>
              </label>
              {form.create_security_group && (
                <div>
                  <label style={{ display: "flex", flexDirection: "column", gap: 4, maxWidth: 300 }}>
                    <span style={{ fontSize: 13, fontWeight: 500 }}>Security Group Name</span>
                    <input value={form.security_group_name}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => updateForm("security_group_name", e.target.value)}
                      placeholder="default-sg" style={inputStyle} />
                  </label>

                  {/* Default rules table */}
                  <div style={{ marginTop: 12 }}>
                    <strong style={{ fontSize: 13, color: "var(--pf9-text)" }}>Default Rules (always applied):</strong>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, marginTop: 8 }}>
                      <thead>
                        <tr style={{ background: "var(--pf9-bg-header)", textAlign: "left" }}>
                          <th style={{ padding: "6px 8px" }}>Direction</th>
                          <th style={{ padding: "6px 8px" }}>Protocol</th>
                          <th style={{ padding: "6px 8px" }}>Port</th>
                          <th style={{ padding: "6px 8px" }}>Description</th>
                        </tr>
                      </thead>
                      <tbody>
                        {DEFAULT_SG_RULES_DISPLAY.map((r, i) => (
                          <tr key={i} style={{ borderBottom: "1px solid var(--pf9-border)" }}>
                            <td style={{ padding: "6px 8px" }}>{r.direction}</td>
                            <td style={{ padding: "6px 8px" }}>{r.protocol}</td>
                            <td style={{ padding: "6px 8px" }}>{r.port}</td>
                            <td style={{ padding: "6px 8px" }}>{r.desc}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {/* Custom rules */}
                  {form.custom_sg_rules.length > 0 && (
                    <div style={{ marginTop: 12 }}>
                      <strong style={{ fontSize: 13 }}>Custom Rules:</strong>
                      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, marginTop: 8 }}>
                        <thead>
                          <tr style={{ background: "var(--pf9-bg-header)", textAlign: "left" }}>
                            <th style={{ padding: "6px 8px" }}>Dir</th>
                            <th style={{ padding: "6px 8px" }}>Proto</th>
                            <th style={{ padding: "6px 8px" }}>Port(s)</th>
                            <th style={{ padding: "6px 8px" }}>Source</th>
                            <th style={{ padding: "6px 8px" }}>Desc</th>
                            <th style={{ padding: "6px 8px" }}></th>
                          </tr>
                        </thead>
                        <tbody>
                          {form.custom_sg_rules.map((r, i) => (
                            <tr key={i} style={{ borderBottom: "1px solid var(--pf9-border)" }}>
                              <td style={{ padding: "6px 8px" }}>{r.direction}</td>
                              <td style={{ padding: "6px 8px" }}>{r.protocol}</td>
                              <td style={{ padding: "6px 8px" }}>
                                {r.port_range_min ? (r.port_range_min === r.port_range_max ? r.port_range_min : `${r.port_range_min}-${r.port_range_max}`) : "All"}
                              </td>
                              <td style={{ padding: "6px 8px" }}>{r.remote_ip_prefix}</td>
                              <td style={{ padding: "6px 8px" }}>{r.description}</td>
                              <td style={{ padding: "6px 8px" }}>
                                <button onClick={() => removeCustomRule(i)}
                                  style={{ background: "var(--pf9-danger-bg)", border: "none", borderRadius: 4, padding: "2px 6px", color: "var(--pf9-danger-text)", cursor: "pointer" }}>✕</button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* Quick presets */}
                  <div style={{ marginTop: 12 }}>
                    <strong style={{ fontSize: 13 }}>Quick Add:</strong>
                    <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 6 }}>
                      {COMMON_PORT_PRESETS.map((p) => (
                        <button key={p.label} onClick={() => addPresetRule(p)}
                          style={{ padding: "4px 10px", borderRadius: 12, border: "1px solid var(--pf9-border)",
                            background: "var(--pf9-bg-card)", fontSize: 11, cursor: "pointer", color: "var(--pf9-text)" }}>
                          + {p.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Add custom rule form */}
                  <div style={{ marginTop: 16, padding: 12, background: "var(--pf9-bg-header)", borderRadius: 8, border: "1px dashed var(--pf9-border)" }}>
                    <strong style={{ fontSize: 13, display: "block", marginBottom: 8 }}>Add Custom Rule:</strong>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr) auto", gap: 6, alignItems: "end" }}>
                      <label style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                        <span style={{ fontSize: 11 }}>Direction</span>
                        <select value={newRule.direction}
                          onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setNewRule({ ...newRule, direction: e.target.value as "ingress" | "egress" })}
                          style={inputStyleSm}>
                          <option value="ingress">Ingress</option>
                          <option value="egress">Egress</option>
                        </select>
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                        <span style={{ fontSize: 11 }}>Protocol</span>
                        <select value={newRule.protocol}
                          onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setNewRule({ ...newRule, protocol: e.target.value })}
                          style={inputStyleSm}>
                          <option value="tcp">TCP</option>
                          <option value="udp">UDP</option>
                          <option value="icmp">ICMP</option>
                        </select>
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                        <span style={{ fontSize: 11 }}>Port Min</span>
                        <input type="number" value={newRule.port_range_min || ""}
                          onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewRule({ ...newRule, port_range_min: parseInt(e.target.value) || null })}
                          style={inputStyleSm} placeholder="e.g. 8080" />
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                        <span style={{ fontSize: 11 }}>Port Max</span>
                        <input type="number" value={newRule.port_range_max || ""}
                          onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewRule({ ...newRule, port_range_max: parseInt(e.target.value) || null })}
                          style={inputStyleSm} placeholder="e.g. 8080" />
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                        <span style={{ fontSize: 11 }}>Description</span>
                        <input value={newRule.description}
                          onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewRule({ ...newRule, description: e.target.value })}
                          style={inputStyleSm} placeholder="Optional" />
                      </label>
                      <button onClick={addCustomRule}
                        style={{ ...btnStyleSm, background: "#4299e1", height: 32 }}>Add</button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        );

      // ── Step 4: Review & Provision ──
      case 4: {
        const allRecipients = [
          ...(form.include_user_email && form.user_email ? [form.user_email] : []),
          ...form.email_recipients.split(",").map((s: string) => s.trim()).filter(Boolean),
        ].filter(Boolean);

        return (
          <div style={{ display: "grid", gap: 16 }}>
            <h3 style={{ margin: 0, color: "var(--pf9-text)" }}>✅ Review & Provision</h3>
            <p style={{ margin: 0, fontSize: 13, color: "var(--pf9-text-secondary)" }}>
              Review the configuration below. Click "Provision Customer" to begin.
            </p>

            {/* Summary cards row 1 */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
              <div style={summaryCard}>
                <h4 style={summaryTitle}>🏢 Domain & Project</h4>
                <div style={summaryRow}><span>Domain:</span> <strong>{form.domain_name}{form.existing_domain_id && " (existing)"}</strong></div>
                <div style={summaryRow}><span>Project:</span> <strong>{form.project_name}</strong></div>
                {form.subscription_id && <div style={summaryRow}><span>Subscription:</span> <strong>{form.subscription_id}</strong></div>}
              </div>
              <div style={summaryCard}>
                <h4 style={summaryTitle}>👤 User</h4>
                <div style={summaryRow}><span>Username:</span> <strong>{form.username}</strong></div>
                <div style={summaryRow}><span>Email:</span> <strong>{form.user_email || "\u2014"}</strong></div>
                <div style={summaryRow}><span>Role:</span> <strong>{keystoneRoles.find(r => r.name === form.user_role)?.label || form.user_role}</strong></div>
                <div style={summaryRow}><span>Password:</span> <strong>{form.user_password ? "Custom" : "Auto-generated"}</strong></div>
              </div>
              <div style={summaryCard}>
                <h4 style={summaryTitle}>🌐 Network</h4>
                {form.create_network ? (<>
                  <div style={summaryRow}><span>Type:</span> <strong>{form.network_type.toUpperCase()}</strong></div>
                  <div style={summaryRow}><span>Physical Net:</span> <strong>{form.physical_network}</strong></div>
                  <div style={summaryRow}><span>CIDR:</span> <strong>{form.subnet_cidr}</strong></div>
                  {form.vlan_id && <div style={summaryRow}><span>VLAN ID:</span> <strong>{form.vlan_id}</strong></div>}
                  <div style={summaryRow}><span>DHCP:</span> <strong>{form.enable_dhcp ? "Enabled" : "Disabled"}</strong></div>
                  {form.enable_dhcp && form.allocation_pool_start && form.allocation_pool_end && (
                    <div style={summaryRow}><span>Allocation Pool:</span> <strong>{form.allocation_pool_start} — {form.allocation_pool_end}</strong></div>
                  )}
                </>) : <div style={{ fontSize: 13, color: "var(--pf9-text-muted)" }}>Skipped</div>}
              </div>
            </div>

            {/* Quotas */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
              <div style={summaryCard}>
                <h4 style={summaryTitle}>🖥️ Compute Quotas</h4>
                {Object.entries(form.compute_quotas).map(([k, v]) => (
                  <div key={k} style={summaryRow}>
                    <span>{QUOTA_LABELS[k] || k}:</span>
                    <strong>{v === -1 ? "Unlimited" : k === "ram" ? `${v} GiB` : v}</strong>
                  </div>
                ))}
              </div>
              <div style={summaryCard}>
                <h4 style={summaryTitle}>💾 Block Storage Quotas</h4>
                {Object.entries(form.storage_quotas).map(([k, v]) => (
                  <div key={k} style={summaryRow}><span>{QUOTA_LABELS[k] || k}:</span> <strong>{v === -1 ? "Unlimited" : v}</strong></div>
                ))}
              </div>
              <div style={summaryCard}>
                <h4 style={summaryTitle}>🌐 Network Quotas</h4>
                {Object.entries(form.network_quotas).map(([k, v]) => (
                  <div key={k} style={summaryRow}><span>{QUOTA_LABELS[k] || k}:</span> <strong>{v === -1 ? "Unlimited" : v}</strong></div>
                ))}
              </div>
            </div>

            {/* Security group */}
            {form.create_security_group && (
              <div style={{ fontSize: 13, color: "var(--pf9-text-secondary)", background: "var(--pf9-bg-card)", padding: 12, borderRadius: 8, border: "1px solid var(--pf9-border)" }}>
                🔒 Security Group <strong>{form.security_group_name}</strong> — default rules (SSH, ICMP, HTTP, HTTPS, all egress)
                {form.custom_sg_rules.length > 0 && (<>
                  {" "}+ <strong>{form.custom_sg_rules.length}</strong> custom rule(s):
                  <ul style={{ margin: "4px 0 0", paddingLeft: 20, fontSize: 12 }}>
                    {form.custom_sg_rules.map((r, i) => (
                      <li key={i}>{r.direction.toUpperCase()} {r.protocol.toUpperCase()}{" "}
                        {r.port_range_min ? (r.port_range_min === r.port_range_max ? r.port_range_min : `${r.port_range_min}-${r.port_range_max}`) : "All"}{" "}
                        — {r.description || "Custom"}</li>
                    ))}
                  </ul>
                </>)}
              </div>
            )}

            {/* Email */}
            {form.send_welcome_email && (
              <div style={{ fontSize: 13, color: "var(--pf9-text-secondary)", background: "var(--pf9-bg-card)", padding: 12, borderRadius: 8, border: "1px solid var(--pf9-border)" }}>
                📧 Welcome email (with full provisioning details) will be sent to: <strong>{allRecipients.join(", ") || "No recipients configured"}</strong>
              </div>
            )}

            {/* Provision result */}
            {provisionResult && (
              <div style={{ padding: 16, borderRadius: 8,
                border: `2px solid ${provisionResult.status === "completed" ? "#48bb78" : "#fc8181"}`,
                background: provisionResult.status === "completed" ? "#f0fff4" : "#fff5f5" }}>
                <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 8 }}>
                  {provisionResult.status === "completed" ? "✅ Provisioning Completed!" : "❌ Provisioning Failed"}
                </div>
                {provisionResult.error && <div style={{ color: "var(--pf9-danger-text)", fontSize: 13 }}>{provisionResult.error}</div>}
                {provisionResult.job_id && <div style={{ fontSize: 13, marginTop: 8, color: "var(--pf9-text-secondary)" }}>Job ID: {provisionResult.job_id}</div>}
                <button onClick={resetWizard} style={{ marginTop: 12, ...btnStyle, background: "#4299e1" }}>Provision Another Customer</button>
              </div>
            )}

            {/* Provision button */}
            {!provisionResult && (
              <button onClick={handleProvision}
                disabled={provisioning || !form.domain_name || !form.project_name || !form.username}
                style={{ ...btnStyle, background: provisioning ? "var(--pf9-text-muted)" : "#38a169", fontSize: 16, padding: "14px 32px", cursor: provisioning ? "wait" : "pointer" }}>
                {provisioning ? "⏳ Provisioning... Please wait" : "🚀 Provision Customer"}
              </button>
            )}
          </div>
        );
      }

      default: return null;
    }
  };

  // ── Validation per step ──
  const canProceed = (): boolean => {
    switch (wizardStep) {
      case 0:
        if (!form.domain_name.trim() || !form.subscription_id.trim() || !form.project_name.trim()) return false;
        if (domainCheck?.exists && !domainAction) return false;
        if (projectCheck?.exists) return false;
        return true;
      case 1: return !!form.username.trim();
      default: return true;
    }
  };

  // ====================
  // RENDER
  // ====================
  return (
    <div style={{ padding: "0 8px" }}>
      {/* View toggle */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16, borderBottom: "2px solid var(--pf9-border)", paddingBottom: 8 }}>
        <button onClick={() => setActiveView("wizard")}
          style={{ ...tabBtn, borderBottom: activeView === "wizard" ? "3px solid var(--pf9-toggle-active)" : "3px solid transparent", fontWeight: activeView === "wizard" ? 700 : 400 }}>
          🚀 Provision Customer
        </button>
        <button onClick={() => { setActiveView("logs"); fetchLogs(); }}
          style={{ ...tabBtn, borderBottom: activeView === "logs" ? "3px solid var(--pf9-toggle-active)" : "3px solid transparent", fontWeight: activeView === "logs" ? 700 : 400 }}>
          📋 Provisioning Logs ({jobsTotal})
        </button>
      </div>

      {/* ── WIZARD VIEW ── */}
      {activeView === "wizard" && (
        <div>
          <div style={{ display: "flex", gap: 4, marginBottom: 24, flexWrap: "wrap" }}>
            {WIZARD_STEPS.map((label, idx) => (
              <button key={idx} onClick={() => setWizardStep(idx)}
                style={{ padding: "8px 16px", borderRadius: 20, border: "1px solid var(--pf9-border)",
                  background: idx === wizardStep ? "var(--pf9-toggle-active)" : idx < wizardStep ? "var(--pf9-success)" : "var(--pf9-bg-card)",
                  color: idx <= wizardStep ? "white" : "var(--pf9-text)",
                  fontSize: 12, fontWeight: idx === wizardStep ? 700 : 400, cursor: "pointer", transition: "all 0.2s" }}>
                {idx + 1}. {label}
              </button>
            ))}
          </div>
          <div style={{ background: "var(--pf9-bg-card)", border: "1px solid var(--pf9-border)", borderRadius: 8, padding: 24, minHeight: 300 }}>
            {renderStepContent()}
          </div>
          {wizardStep < 4 && (
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 16 }}>
              <button onClick={() => setWizardStep(Math.max(0, wizardStep - 1))} disabled={wizardStep === 0}
                style={{ ...btnStyle, background: wizardStep === 0 ? "var(--pf9-toggle-inactive)" : "var(--pf9-text-secondary)" }}>← Previous</button>
              <button onClick={() => setWizardStep(Math.min(WIZARD_STEPS.length - 1, wizardStep + 1))} disabled={!canProceed()}
                style={{ ...btnStyle, background: canProceed() ? "var(--pf9-toggle-active)" : "var(--pf9-toggle-inactive)" }}>Next →</button>
            </div>
          )}
        </div>
      )}

      {/* ── LOGS VIEW ── */}
      {activeView === "logs" && (
        <div>
          {jobsLoading ? (
            <div style={{ textAlign: "center", padding: 40, color: "var(--pf9-text-muted)" }}>Loading...</div>
          ) : jobs.length === 0 ? (
            <div style={{ textAlign: "center", padding: 40, color: "var(--pf9-text-muted)" }}>No provisioning jobs yet</div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: selectedJob ? "1fr 1fr" : "1fr", gap: 16 }}>
              <div>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                  <thead>
                    <tr style={{ background: "var(--pf9-bg-header)", textAlign: "left" }}>
                      <th style={thStyle}>Domain</th><th style={thStyle}>Project</th>
                      <th style={thStyle}>User</th><th style={thStyle}>Status</th>
                      <th style={thStyle}>Created</th><th style={thStyle}>By</th>
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.map((job) => (
                      <tr key={job.job_id} onClick={() => setSelectedJob(job.job_id)}
                        style={{ cursor: "pointer", background: selectedJob === job.job_id ? "var(--pf9-bg-selected)" : "transparent",
                          borderBottom: "1px solid var(--pf9-border)" }}>
                        <td style={tdStyle}>{job.domain_name}</td>
                        <td style={tdStyle}>{job.project_name}</td>
                        <td style={tdStyle}>{job.username}</td>
                        <td style={tdStyle}>{statusBadge(job.status)}</td>
                        <td style={tdStyle}>{fmtDate(job.created_at)}</td>
                        <td style={tdStyle}>{job.created_by}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {selectedJob && jobDetail && (
                <div style={{ background: "var(--pf9-bg-card)", border: "1px solid var(--pf9-border)", borderRadius: 8, padding: 16 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                    <h3 style={{ margin: 0, fontSize: 16 }}>Job Details</h3>
                    <button onClick={() => setSelectedJob(null)}
                      style={{ background: "none", border: "none", fontSize: 18, cursor: "pointer", color: "var(--pf9-text-secondary)" }}>✕</button>
                  </div>
                  <div style={{ fontSize: 13, marginBottom: 16 }}>
                    <div><strong>Status:</strong> {statusBadge(jobDetail.status)}</div>
                    <div style={{ marginTop: 4 }}><strong>Started:</strong> {fmtDate(jobDetail.started_at)}</div>
                    <div><strong>Completed:</strong> {fmtDate(jobDetail.completed_at)}</div>
                    {jobDetail.error_message && (
                      <div style={{ color: "#c53030", marginTop: 8, padding: 8, background: "#fff5f5", borderRadius: 4 }}>
                        <strong>Error:</strong> {jobDetail.error_message}
                      </div>
                    )}
                  </div>
                  <h4 style={{ margin: "0 0 8px 0", fontSize: 14 }}>Provisioning Steps</h4>
                  <div style={{ display: "grid", gap: 8 }}>
                    {jobSteps.map((s) => (
                      <div key={s.step_number} style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: 8, borderRadius: 6,
                        background: s.status === "completed" ? "var(--pf9-safe-bg)" : s.status === "failed" ? "var(--pf9-danger-bg)" : s.status === "running" ? "var(--pf9-info-bg)" : "var(--pf9-bg-card)",
                        border: `1px solid ${s.status === "completed" ? "var(--pf9-safe-border)" : s.status === "failed" ? "var(--pf9-danger-border)" : "var(--pf9-border)"}`, fontSize: 12 }}>
                        <div style={{ fontWeight: 700, minWidth: 24 }}>
                          {s.status === "completed" ? "✅" : s.status === "failed" ? "❌" : s.status === "running" ? "⏳" : "⬜"}
                        </div>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontWeight: 600 }}>Step {s.step_number}: {s.description}</div>
                          {s.resource_id && <div style={{ color: "var(--pf9-text-secondary)", marginTop: 2 }}>Resource: {s.resource_id}</div>}
                          {s.error && <div style={{ color: "var(--pf9-danger-text)", marginTop: 2 }}>{s.error}</div>}
                        </div>
                        <div style={{ color: "var(--pf9-text-muted)", whiteSpace: "nowrap" }}>{fmtDate(s.completed_at || s.started_at)}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------
const inputStyle: React.CSSProperties = {
  padding: "8px 12px", borderRadius: 6,
  border: "1px solid var(--pf9-border)",
  background: "var(--pf9-bg-input)",
  color: "var(--pf9-text)", fontSize: 14,
};
const inputStyleSm: React.CSSProperties = {
  padding: "5px 8px", borderRadius: 4,
  border: "1px solid var(--pf9-border)",
  background: "var(--pf9-bg-input)",
  color: "var(--pf9-text)", fontSize: 12,
};
const btnStyle: React.CSSProperties = {
  padding: "10px 24px", border: "none", borderRadius: 6,
  color: "white", fontWeight: 600, fontSize: 14, cursor: "pointer",
};
const btnStyleSm: React.CSSProperties = {
  padding: "6px 14px", border: "none", borderRadius: 4,
  color: "white", fontWeight: 600, fontSize: 12, cursor: "pointer",
};
const tabBtn: React.CSSProperties = {
  background: "none", border: "none", padding: "8px 16px",
  fontSize: 14, cursor: "pointer", color: "var(--pf9-text)",
};
const thStyle: React.CSSProperties = {
  padding: "10px 12px", fontWeight: 600,
  borderBottom: "2px solid var(--pf9-border)",
};
const tdStyle: React.CSSProperties = { padding: "10px 12px" };
const summaryCard: React.CSSProperties = {
  background: "var(--pf9-bg-card)", borderRadius: 8,
  padding: 16, border: "1px solid var(--pf9-border)",
};
const summaryTitle: React.CSSProperties = {
  margin: "0 0 12px 0", fontSize: 14, color: "var(--pf9-heading)",
};
const summaryRow: React.CSSProperties = {
  display: "flex", justifyContent: "space-between",
  fontSize: 13, padding: "3px 0", color: "var(--pf9-text-secondary)",
};

export default CustomerProvisioningTab;
