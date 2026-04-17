import { useEffect, useState } from "react";
import {
  apiProvisionResources, apiProvisionVm,
  type ProvisionResources, type FlavorOption, type ImageOption, type NetworkOption,
} from "../lib/api";

// ── Helpers ─────────────────────────────────────────────────────────────────

function fmtRam(mb: number) {
  return mb >= 1024 ? `${(mb / 1024).toFixed(0)} GB` : `${mb} MB`;
}

/** Validate VM name: lowercase, digits, hyphens, start with letter/digit, max 63 chars */
function validateVmName(name: string): string | null {
  if (!name) return null;
  if (name.length > 63) return "Max 63 characters";
  if (!/^[a-z0-9]/.test(name)) return "Must start with a letter or digit";
  if (!/^[a-z0-9][a-z0-9-]*$/.test(name)) return "Only lowercase letters, numbers, and hyphens allowed";
  return null;
}

/** Generate cloud-config YAML for initial user */
function buildCloudInit(user: string, password: string, existingData: string): string {
  if (!user && !password) return existingData;
  const lines = ["#cloud-config", "users:"];
  lines.push(`  - name: ${user || "cloud-user"}`);
  if (password) {
    lines.push(`    lock_passwd: false`);
    lines.push(`    plain_text_passwd: '${password}'`);
  }
  lines.push("    sudo: ALL=(ALL) NOPASSWD:ALL");
  lines.push("chpasswd:");
  lines.push("  expire: false");
  return lines.join("\n");
}

// ── Main component ───────────────────────────────────────────────────────────

export function Provision() {
  const [resources, setResources] = useState<ProvisionResources | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Form fields
  const [vmName, setVmName]         = useState("");
  const [flavorId, setFlavorId]     = useState("");
  const [imageId, setImageId]       = useState("");
  const [networkId, setNetworkId]   = useState("");
  const [sgIds, setSgIds]           = useState<string[]>([]);
  const [userData, setUserData]     = useState("");
  const [count, setCount]           = useState(1);
  const [showAdvanced, setShowAdvanced] = useState(false);
  // New fields
  const [fixedIp, setFixedIp]               = useState("");
  const [cloudInitUser, setCloudInitUser]   = useState("");
  const [cloudInitPass, setCloudInitPass]   = useState("");

  // Submission state
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [created, setCreated] = useState<Array<{ id: string; name: string; status: string }> | null>(null);

  useEffect(() => {
    setLoading(true);
    apiProvisionResources()
      .then((r) => {
        setResources(r);
        // Pre-select first defaults
        if (r.flavors.length > 0)  setFlavorId(r.flavors[0].id);
        if (r.networks.length > 0) setNetworkId(r.networks[0].id);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load resources"))
      .finally(() => setLoading(false));
  }, []);

  const nameError = validateVmName(vmName);

  const selectedFlavor: FlavorOption | undefined = resources?.flavors.find((f) => f.id === flavorId);
  const selectedImage:  ImageOption  | undefined = resources?.images.find((i) => i.id === imageId);
  const selectedNetwork: NetworkOption | undefined = resources?.networks.find((n) => n.id === networkId);

  const toggleSg = (id: string) => {
    setSgIds((ids) => ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]);
  };

  const handleSubmit = async () => {
    if (!vmName.trim())  { setSubmitError("VM name is required"); return; }
    if (nameError)       { setSubmitError(nameError); return; }
    if (!flavorId)       { setSubmitError("Select a flavor"); return; }
    if (!imageId)        { setSubmitError("Select an image"); return; }
    if (!networkId)      { setSubmitError("Select a network"); return; }

    // Build cloud-init user data
    const finalUserData = cloudInitUser || cloudInitPass
      ? buildCloudInit(cloudInitUser, cloudInitPass, userData)
      : userData || undefined;

    setSubmitting(true);
    setSubmitError(null);
    try {
      const result = await apiProvisionVm({
        name: vmName.trim(),
        flavor_id: flavorId,
        image_id: imageId,
        network_id: networkId,
        security_group_ids: sgIds,
        user_data: finalUserData,
        fixed_ip: fixedIp || undefined,
        count,
      });
      setCreated(result.created);
    } catch (e: unknown) {
      setSubmitError(e instanceof Error ? e.message : "Provisioning failed");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <div className="empty-state"><span className="loading-spinner" /></div>;
  if (error)   return <div className="error-banner">{error}</div>;
  if (!resources) return null;

  if (created) {
    return (
      <div className="card" style={{ maxWidth: 600, margin: "2rem auto" }}>
        <div style={{ fontSize: "2rem", textAlign: "center", marginBottom: "1rem" }}>🚀</div>
        <h2 style={{ textAlign: "center", marginBottom: ".5rem" }}>VM{created.length > 1 ? "s" : ""} Provisioned</h2>
        <p style={{ textAlign: "center", color: "var(--color-text-secondary)", marginBottom: "1.5rem" }}>
          Your {created.length === 1 ? "VM is" : `${created.length} VMs are`} now being created. It may take a few minutes to reach the active state.
        </p>
        <div className="card table-wrap" style={{ padding: 0, marginBottom: "1.5rem" }}>
          <table>
            <thead><tr><th>Name</th><th>Status</th></tr></thead>
            <tbody>
              {created.map((vm) => (
                <tr key={vm.id}>
                  <td style={{ fontWeight: 500 }}>{vm.name}</td>
                  <td><span className="badge badge-amber">{vm.status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ textAlign: "center" }}>
          <button className="btn btn-primary" onClick={() => { setCreated(null); setVmName(""); setCount(1); }}>
            Provision Another
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 680, margin: "0 auto" }}>
      <div className="card" style={{ marginBottom: "1rem" }}>
        <h2 style={{ fontSize: "1.05rem", fontWeight: 600, marginBottom: "1.5rem" }}>New Virtual Machine</h2>

        {/* VM Name + Count */}
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "1rem", marginBottom: "1.25rem" }}>
          <div>
            <label style={{ fontSize: ".85rem", fontWeight: 600 }}>
              VM Name *
              <input
                className={`input${nameError ? " input-error" : ""}`}
                type="text"
                placeholder="my-web-server"
                maxLength={63}
                value={vmName}
                onChange={(e) => setVmName(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))}
              />
            </label>
            {nameError ? (
              <div style={{ fontSize: ".73rem", color: "var(--color-danger)", marginTop: ".2rem" }}>{nameError}</div>
            ) : (
              <div style={{ fontSize: ".73rem", color: "var(--color-text-secondary)", marginTop: ".2rem" }}>
                Lowercase letters, numbers and hyphens only — max 63 chars
              </div>
            )}
          </div>
          <label style={{ fontSize: ".85rem", fontWeight: 600 }}>
            Count (1–10)
            <input className="input" type="number" min={1} max={10}
              value={count} onChange={(e) => setCount(Math.max(1, Math.min(10, Number(e.target.value))))} />
          </label>
        </div>

        {/* Flavor */}
        <div style={{ marginBottom: "1.25rem" }}>
          <div style={{ fontSize: ".85rem", fontWeight: 600, marginBottom: ".5rem" }}>Flavor *</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: ".5rem" }}>
            {resources.flavors.map((f) => (
              <button key={f.id}
                onClick={() => setFlavorId(f.id)}
                style={{
                  padding: ".5rem .75rem",
                  border: `2px solid ${f.id === flavorId ? "var(--brand-primary)" : "var(--color-border)"}`,
                  borderRadius: ".5rem",
                  background: f.id === flavorId ? "var(--brand-primary-faint, rgba(79,124,247,.08))" : "var(--color-surface)",
                  cursor: "pointer",
                  textAlign: "left",
                }}>
                <div style={{ fontWeight: 600, fontSize: ".85rem" }}>{f.name}</div>
                <div style={{ fontSize: ".75rem", color: "var(--color-text-secondary)" }}>
                  {f.vcpus} vCPU · {fmtRam(f.ram_mb)}
                </div>
                {f.disk_gb ? (
                  <div style={{ fontSize: ".7rem", color: "var(--color-text-secondary)", marginTop: ".1rem" }}>
                    {f.disk_gb} GB boot volume
                  </div>
                ) : null}
              </button>
            ))}
          </div>
        </div>

        {/* Image */}
        <div style={{ marginBottom: "1.25rem" }}>
          <label style={{ fontSize: ".85rem", fontWeight: 600 }}>
            Image *
            <select className="select" value={imageId} onChange={(e) => setImageId(e.target.value)}>
              <option value="">— Select image —</option>
              {resources.images.map((img) => (
                <option key={img.id} value={img.id}>{img.name}</option>
              ))}
            </select>
          </label>
          {selectedImage && (
            <div style={{ fontSize: ".75rem", color: "var(--color-text-secondary)", marginTop: ".25rem" }}>
              OS: {selectedImage.os_distro || "unknown"}
            </div>
          )}
        </div>

        {/* Network + Fixed IP */}
        <div style={{ marginBottom: "1.25rem" }}>
          <label style={{ fontSize: ".85rem", fontWeight: 600 }}>
            Network *
            <select className="select" value={networkId} onChange={(e) => { setNetworkId(e.target.value); setFixedIp(""); }}>
              <option value="">— Select network —</option>
              {resources.networks.map((n) => (
                <option key={n.id} value={n.id}>{n.name}{n.is_shared ? " (shared)" : ""}</option>
              ))}
            </select>
          </label>
          {selectedNetwork && (
            <div style={{ marginTop: ".5rem" }}>
              <label style={{ fontSize: ".85rem", fontWeight: 600 }}>
                Fixed IP (optional)
                <input
                  className="input"
                  type="text"
                  placeholder={selectedNetwork.subnets && selectedNetwork.subnets.length > 0
                    ? `e.g. within ${selectedNetwork.subnets[0].cidr}`
                    : "Leave blank for auto-assign"}
                  value={fixedIp}
                  onChange={(e) => setFixedIp(e.target.value.trim())}
                />
              </label>
              {selectedNetwork.subnets && selectedNetwork.subnets.length > 0 && (
                <div style={{ fontSize: ".73rem", color: "var(--color-text-secondary)", marginTop: ".2rem" }}>
                  Subnets: {selectedNetwork.subnets.map((s) => `${s.name} (${s.cidr})`).join(", ")}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Security Groups */}
        {resources.security_groups.length > 0 && (
          <div style={{ marginBottom: "1.25rem" }}>
            <div style={{ fontSize: ".85rem", fontWeight: 600, marginBottom: ".5rem" }}>Security Groups</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: ".4rem" }}>
              {resources.security_groups.map((sg) => (
                <label key={sg.id} style={{ display: "flex", alignItems: "center", gap: ".3rem", cursor: "pointer", fontSize: ".85rem" }}>
                  <input type="checkbox" checked={sgIds.includes(sg.id)} onChange={() => toggleSg(sg.id)} />
                  {sg.name}
                </label>
              ))}
            </div>
          </div>
        )}

        {/* Cloud-init + Advanced */}
        <div style={{ marginBottom: "1.25rem" }}>
          <button className="btn btn-ghost btn-sm" onClick={() => setShowAdvanced((v) => !v)}>
            {showAdvanced ? "▲ Hide advanced" : "▼ Advanced (cloud-init / user data)"}
          </button>
          {showAdvanced && (
            <div style={{ marginTop: ".75rem", display: "flex", flexDirection: "column", gap: ".75rem" }}>
              {/* Cloud-init user/password */}
              <div>
                <div style={{ fontSize: ".85rem", fontWeight: 600, marginBottom: ".5rem" }}>Initial User (cloud-init)</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: ".75rem" }}>
                  <label style={{ fontSize: ".85rem" }}>
                    Username
                    <input className="input" type="text" placeholder="e.g. admin"
                      value={cloudInitUser} onChange={(e) => setCloudInitUser(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ""))} />
                  </label>
                  <label style={{ fontSize: ".85rem" }}>
                    Password
                    <input className="input" type="password" placeholder="Leave blank to skip"
                      value={cloudInitPass} onChange={(e) => setCloudInitPass(e.target.value)} autoComplete="new-password" />
                  </label>
                </div>
                <div style={{ fontSize: ".73rem", color: "var(--color-text-secondary)", marginTop: ".25rem" }}>
                  Creates a sudo user on first boot. Leave blank to use the image default.
                </div>
              </div>

              {/* Raw user-data override */}
              <label style={{ fontSize: ".85rem", fontWeight: 600 }}>
                Custom user data (overrides above if filled)
                <textarea className="input" rows={4} placeholder="#cloud-config&#10;..." style={{ fontFamily: "monospace", fontSize: ".8rem", resize: "vertical" }}
                  value={userData} onChange={(e) => setUserData(e.target.value)} />
              </label>
            </div>
          )}
        </div>

        {/* Summary */}
        {selectedFlavor && selectedImage && networkId && (
          <div style={{ background: "var(--color-surface-raised)", borderRadius: ".5rem", padding: ".75rem 1rem", marginBottom: "1rem", fontSize: ".85rem" }}>
            <strong>{count}× {vmName || "vm"}</strong>
            {" · "}{selectedFlavor.name} ({selectedFlavor.vcpus} vCPU / {fmtRam(selectedFlavor.ram_mb)}
            {selectedFlavor.disk_gb ? ` / ${selectedFlavor.disk_gb} GB boot volume` : ""})
            {" · "}{selectedImage.name}
            {fixedIp && ` · IP: ${fixedIp}`}
            {sgIds.length > 0 && ` · ${sgIds.length} SG(s)`}
            {(cloudInitUser || userData) && " · cloud-init configured"}
          </div>
        )}

        {submitError && <div className="error-banner" style={{ marginBottom: ".75rem" }}>{submitError}</div>}

        <button className="btn btn-primary" onClick={handleSubmit} disabled={submitting || !vmName || !flavorId || !imageId || !networkId}>
          {submitting ? "Provisioning…" : `🚀 Create${count > 1 ? ` ${count} VMs` : " VM"}`}
        </button>
      </div>

      {/* Info card */}
      <div className="card" style={{ fontSize: ".85rem", color: "var(--color-text-secondary)" }}>
        <p style={{ margin: 0 }}>
          VMs are created as your tenant admin. Each VM boots from a new block volume created from the selected image.
          Once launched, the VM will appear in <strong>My Infrastructure</strong> after the next inventory sync (typically within 2–5 minutes).
        </p>
      </div>
    </div>
  );
}
