/**
 * MFASettings – Self-service MFA enrollment / management component.
 *
 * Features:
 *   - Setup MFA with Google Authenticator (QR code enrollment)
 *   - Verify initial setup with a TOTP code
 *   - Display one-time backup codes after enrollment
 *   - Disable MFA (requires current TOTP code)
 *   - Admin view: see MFA status for all users
 */

import React, { useState, useEffect, useCallback } from "react";

const API_BASE = (window as any).__PF9_API_BASE__ || import.meta.env.VITE_API_BASE || "/api";

interface MFAStatus {
  mfa_enabled: boolean;
  has_backup_codes: boolean;
}

interface MFASetupResponse {
  totp_secret: string;
  qr_code_base64: string;
  provisioning_uri: string;
}

interface MFAVerifySetupResponse {
  message: string;
  backup_codes: string[];
}

interface MFAUserEntry {
  username: string;
  mfa_enabled: boolean;
  created_at: string | null;
}

interface Props {
  isOpen: boolean;
  onClose: () => void;
  isAdmin?: boolean;
}

const MFASettings: React.FC<Props> = ({ isOpen, onClose, isAdmin }) => {
  const [status, setStatus] = useState<MFAStatus | null>(null);
  const [setupData, setSetupData] = useState<MFASetupResponse | null>(null);
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
  const [users, setUsers] = useState<MFAUserEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [verifyCode, setVerifyCode] = useState("");
  const [disableCode, setDisableCode] = useState("");
  const [step, setStep] = useState<"status" | "setup" | "verify" | "backup_codes" | "disable" | "users">("status");

  const token = localStorage.getItem("auth_token") || "";
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };

  const clearMessages = () => { setError(""); setSuccess(""); };

  // ── Fetch current user MFA status ──
  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/auth/mfa/status`, { headers });
      if (!res.ok) throw new Error("Failed to fetch MFA status");
      const data: MFAStatus = await res.json();
      setStatus(data);
    } catch (err: any) {
      setError(err.message);
    }
  }, []);

  // ── Fetch admin user list ──
  const fetchUsers = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/auth/mfa/users`, { headers });
      if (!res.ok) throw new Error("Failed to fetch MFA users");
      const data: MFAUserEntry[] = await res.json();
      setUsers(data);
    } catch (err: any) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      clearMessages();
      setStep("status");
      setSetupData(null);
      setBackupCodes(null);
      setVerifyCode("");
      setDisableCode("");
      fetchStatus();
    }
  }, [isOpen, fetchStatus]);

  if (!isOpen) return null;

  // ── Begin MFA Setup ──
  const handleBeginSetup = async () => {
    setLoading(true); clearMessages();
    try {
      const res = await fetch(`${API_BASE}/auth/mfa/setup`, { method: "POST", headers });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Failed to start MFA setup");
      }
      const data: MFASetupResponse = await res.json();
      setSetupData(data);
      setStep("verify");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // ── Verify Setup Code ──
  const handleVerifySetup = async () => {
    if (!verifyCode || verifyCode.length < 6) { setError("Enter a valid 6-digit code"); return; }
    setLoading(true); clearMessages();
    try {
      const res = await fetch(`${API_BASE}/auth/mfa/verify-setup`, {
        method: "POST", headers,
        body: JSON.stringify({ code: verifyCode }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Verification failed");
      }
      const data: MFAVerifySetupResponse = await res.json();
      setBackupCodes(data.backup_codes);
      setStep("backup_codes");
      setSuccess("MFA enabled successfully!");
      await fetchStatus();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // ── Disable MFA ──
  const handleDisable = async () => {
    if (!disableCode || disableCode.length < 6) { setError("Enter a valid code"); return; }
    setLoading(true); clearMessages();
    try {
      const res = await fetch(`${API_BASE}/auth/mfa/disable`, {
        method: "POST", headers,
        body: JSON.stringify({ code: disableCode }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Failed to disable MFA");
      }
      setSuccess("MFA has been disabled.");
      setStep("status");
      setDisableCode("");
      await fetchStatus();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // ── Styles ──
  const overlay: React.CSSProperties = {
    position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)",
    display: "flex", alignItems: "center", justifyContent: "center", zIndex: 10000,
  };
  const modal: React.CSSProperties = {
    background: "var(--card-bg, #fff)", borderRadius: "14px",
    padding: "2rem", width: "520px", maxWidth: "95vw", maxHeight: "90vh",
    overflowY: "auto", boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
    color: "var(--text-primary, #222)",
  };
  const inputStyle: React.CSSProperties = {
    width: "100%", padding: "0.7rem", fontSize: "1.3rem",
    border: "1.5px solid var(--border-color, #ddd)", borderRadius: "8px",
    textAlign: "center", letterSpacing: "0.5em", fontFamily: "monospace",
    background: "var(--input-bg, #fafafa)", color: "var(--text-primary, #333)",
    boxSizing: "border-box", outline: "none",
  };
  const btnPrimary: React.CSSProperties = {
    padding: "0.7rem 1.5rem", fontSize: "0.95rem", fontWeight: 600,
    color: "#fff", background: "linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)",
    border: "none", borderRadius: "8px", cursor: "pointer",
    transition: "transform 0.1s", boxShadow: "0 4px 12px rgba(99,102,241,0.3)",
  };
  const btnSecondary: React.CSSProperties = {
    padding: "0.6rem 1.2rem", fontSize: "0.9rem", fontWeight: 500,
    color: "var(--text-secondary, #666)", background: "var(--btn-secondary-bg, #f0f0f0)",
    border: "1px solid var(--border-color, #ddd)", borderRadius: "8px", cursor: "pointer",
  };
  const btnDanger: React.CSSProperties = {
    ...btnPrimary,
    background: "linear-gradient(135deg, #ef4444 0%, #dc2626 100%)",
    boxShadow: "0 4px 12px rgba(239,68,68,0.3)",
  };

  return (
    <div style={overlay} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={modal} onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
          <h2 style={{ margin: 0, fontSize: "1.3rem" }}>🔐 Two-Factor Authentication</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", fontSize: "1.5rem", cursor: "pointer", color: "var(--text-secondary, #999)" }}>✕</button>
        </div>

        {/* Error / Success Messages */}
        {error && (
          <div style={{ padding: "0.7rem", marginBottom: "1rem", background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)", borderRadius: "8px", color: "#ef4444", fontSize: "0.85rem" }}>
            ⚠️ {error}
          </div>
        )}
        {success && (
          <div style={{ padding: "0.7rem", marginBottom: "1rem", background: "rgba(34,197,94,0.1)", border: "1px solid rgba(34,197,94,0.3)", borderRadius: "8px", color: "#22c55e", fontSize: "0.85rem" }}>
            ✅ {success}
          </div>
        )}

        {/* Navigation for admins */}
        {isAdmin && (
          <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1.5rem" }}>
            <button
              style={{ ...btnSecondary, ...(step !== "users" ? { fontWeight: 700, borderColor: "#6366f1", color: "#6366f1" } : {}) }}
              onClick={() => { setStep("status"); clearMessages(); }}
            >
              My MFA
            </button>
            <button
              style={{ ...btnSecondary, ...(step === "users" ? { fontWeight: 700, borderColor: "#6366f1", color: "#6366f1" } : {}) }}
              onClick={() => { setStep("users"); clearMessages(); fetchUsers(); }}
            >
              All Users
            </button>
          </div>
        )}

        {/* ═══ STATUS VIEW ═══ */}
        {step === "status" && status && (
          <div>
            <div style={{
              padding: "1.25rem", borderRadius: "12px", marginBottom: "1.5rem",
              background: status.mfa_enabled ? "rgba(34,197,94,0.08)" : "rgba(245,158,11,0.08)",
              border: status.mfa_enabled ? "1px solid rgba(34,197,94,0.2)" : "1px solid rgba(245,158,11,0.2)",
              textAlign: "center",
            }}>
              <div style={{ fontSize: "2.5rem", marginBottom: "0.5rem" }}>
                {status.mfa_enabled ? "✅" : "⚠️"}
              </div>
              <p style={{ fontSize: "1.1rem", fontWeight: 600, margin: "0 0 4px" }}>
                {status.mfa_enabled ? "MFA is Enabled" : "MFA is Not Enabled"}
              </p>
              <p style={{ fontSize: "0.85rem", color: "var(--text-secondary, #888)", margin: 0 }}>
                {status.mfa_enabled
                  ? "Your account is protected with two-factor authentication."
                  : "Enable MFA to add an extra layer of security to your account."}
              </p>
            </div>

            {!status.mfa_enabled ? (
              <button style={btnPrimary} onClick={handleBeginSetup} disabled={loading}>
                {loading ? "Setting up..." : "🔐 Enable MFA"}
              </button>
            ) : (
              <button style={btnDanger} onClick={() => { setStep("disable"); clearMessages(); }}>
                🗑️ Disable MFA
              </button>
            )}
          </div>
        )}

        {/* ═══ VERIFY SETUP (QR + code input) ═══ */}
        {step === "verify" && setupData && (
          <div>
            <div style={{ textAlign: "center", marginBottom: "1.5rem" }}>
              <p style={{ fontSize: "0.95rem", marginBottom: "1rem", color: "var(--text-secondary, #555)" }}>
                Scan this QR code with <strong>Google Authenticator</strong> or any TOTP-compatible app:
              </p>
              <img
                src={`data:image/png;base64,${setupData.qr_code_base64}`}
                alt="MFA QR Code"
                style={{ width: "200px", height: "200px", borderRadius: "12px", border: "2px solid var(--border-color, #eee)", padding: "8px", background: "#fff" }}
              />
            </div>

            <details style={{ marginBottom: "1rem" }}>
              <summary style={{ cursor: "pointer", fontSize: "0.85rem", color: "var(--text-secondary, #888)" }}>
                Can't scan? Enter this key manually
              </summary>
              <div style={{
                marginTop: "0.5rem", padding: "0.75rem", background: "var(--input-bg, #f5f5f5)",
                borderRadius: "8px", fontFamily: "monospace", fontSize: "0.9rem",
                wordBreak: "break-all", textAlign: "center", letterSpacing: "0.15em",
              }}>
                {setupData.totp_secret}
              </div>
            </details>

            <div style={{ marginBottom: "1rem" }}>
              <label style={{ display: "block", marginBottom: "6px", fontWeight: 500, fontSize: "0.9rem" }}>
                Enter the 6-digit code from your app:
              </label>
              <input
                type="text" value={verifyCode}
                onChange={(e) => setVerifyCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                placeholder="000000" maxLength={6} autoFocus inputMode="numeric"
                style={inputStyle}
              />
            </div>

            <div style={{ display: "flex", gap: "0.75rem" }}>
              <button style={btnPrimary} onClick={handleVerifySetup} disabled={loading || verifyCode.length < 6}>
                {loading ? "Verifying..." : "✅ Verify & Enable"}
              </button>
              <button style={btnSecondary} onClick={() => { setStep("status"); setSetupData(null); setVerifyCode(""); clearMessages(); }}>
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* ═══ BACKUP CODES ═══ */}
        {step === "backup_codes" && backupCodes && (
          <div>
            <div style={{
              padding: "1rem", borderRadius: "10px", marginBottom: "1rem",
              background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.2)",
            }}>
              <p style={{ fontWeight: 600, margin: "0 0 6px", fontSize: "0.95rem" }}>
                ⚠️ Save Your Backup Codes
              </p>
              <p style={{ fontSize: "0.8rem", color: "var(--text-secondary, #666)", margin: 0 }}>
                These codes can be used to sign in if you lose access to your authenticator app. Each code can only be used once. Store them in a safe place.
              </p>
            </div>

            <div style={{
              display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px",
              padding: "1rem", background: "var(--input-bg, #f5f5f5)",
              borderRadius: "10px", marginBottom: "1.5rem",
            }}>
              {backupCodes.map((code, i) => (
                <div key={i} style={{
                  fontFamily: "monospace", fontSize: "0.95rem",
                  padding: "6px 10px", background: "var(--card-bg, #fff)",
                  borderRadius: "6px", textAlign: "center",
                  border: "1px solid var(--border-color, #e0e0e0)",
                }}>
                  {code}
                </div>
              ))}
            </div>

            <div style={{ display: "flex", gap: "0.75rem" }}>
              <button style={btnPrimary} onClick={() => {
                navigator.clipboard.writeText(backupCodes.join("\n")).then(() => {
                  setSuccess("Backup codes copied to clipboard!");
                }).catch(() => {
                  setError("Failed to copy. Please copy manually.");
                });
              }}>
                📋 Copy Codes
              </button>
              <button style={btnSecondary} onClick={() => { setStep("status"); setBackupCodes(null); }}>
                Done
              </button>
            </div>
          </div>
        )}

        {/* ═══ DISABLE MFA ═══ */}
        {step === "disable" && (
          <div>
            <div style={{
              padding: "1rem", borderRadius: "10px", marginBottom: "1.5rem",
              background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)",
            }}>
              <p style={{ fontWeight: 600, margin: "0 0 6px", fontSize: "0.95rem" }}>
                ⚠️ Disable Two-Factor Authentication
              </p>
              <p style={{ fontSize: "0.85rem", color: "var(--text-secondary, #666)", margin: 0 }}>
                This will remove the extra security layer from your account. Enter your current TOTP code to confirm.
              </p>
            </div>

            <div style={{ marginBottom: "1rem" }}>
              <label style={{ display: "block", marginBottom: "6px", fontWeight: 500, fontSize: "0.9rem" }}>
                Current TOTP Code:
              </label>
              <input
                type="text" value={disableCode}
                onChange={(e) => setDisableCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                placeholder="000000" maxLength={6} autoFocus inputMode="numeric"
                style={inputStyle}
              />
            </div>

            <div style={{ display: "flex", gap: "0.75rem" }}>
              <button style={btnDanger} onClick={handleDisable} disabled={loading || disableCode.length < 6}>
                {loading ? "Disabling..." : "🗑️ Disable MFA"}
              </button>
              <button style={btnSecondary} onClick={() => { setStep("status"); setDisableCode(""); clearMessages(); }}>
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* ═══ ADMIN: ALL USERS ═══ */}
        {step === "users" && (
          <div>
            <h3 style={{ margin: "0 0 1rem", fontSize: "1rem" }}>MFA Status for All Users</h3>
            {users.length === 0 ? (
              <p style={{ color: "var(--text-secondary, #888)", fontSize: "0.9rem" }}>No users found.</p>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: "left", padding: "8px 10px", borderBottom: "2px solid var(--border-color, #eee)", fontWeight: 600 }}>Username</th>
                    <th style={{ textAlign: "center", padding: "8px 10px", borderBottom: "2px solid var(--border-color, #eee)", fontWeight: 600 }}>MFA</th>
                    <th style={{ textAlign: "left", padding: "8px 10px", borderBottom: "2px solid var(--border-color, #eee)", fontWeight: 600 }}>Enrolled</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map(u => (
                    <tr key={u.username}>
                      <td style={{ padding: "8px 10px", borderBottom: "1px solid var(--border-color, #f0f0f0)" }}>{u.username}</td>
                      <td style={{ padding: "8px 10px", borderBottom: "1px solid var(--border-color, #f0f0f0)", textAlign: "center" }}>
                        {u.mfa_enabled
                          ? <span style={{ color: "#22c55e", fontWeight: 600 }}>✅ Enabled</span>
                          : <span style={{ color: "#999" }}>—</span>}
                      </td>
                      <td style={{ padding: "8px 10px", borderBottom: "1px solid var(--border-color, #f0f0f0)", color: "var(--text-secondary, #888)" }}>
                        {u.created_at ? new Date(u.created_at).toLocaleDateString() : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default MFASettings;
