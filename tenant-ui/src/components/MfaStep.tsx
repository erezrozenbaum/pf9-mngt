import React, { useState } from "react";
import type { Branding } from "../lib/api";

interface Props {
  branding: Branding;
  preauthToken: string;
  loading: boolean;
  error: string | null;
  onVerify: (preauthToken: string, code: string) => void;
  onSendEmail: (preauthToken: string) => void;
}

export function MfaStep({ branding, preauthToken, loading, error, onVerify, onSendEmail }: Props) {
  const [code, setCode] = useState("");
  const [emailSent, setEmailSent] = useState(false);

  const handleSend = () => {
    onSendEmail(preauthToken);
    setEmailSent(true);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (loading || !code) return;
    onVerify(preauthToken, code.trim());
  };

  return (
    <div style={styles.page}>
      <div style={styles.card}>
        <div style={styles.brandHeader}>
          {branding.logo_url ? (
            <img src={branding.logo_url} alt={branding.company_name} style={styles.logo} />
          ) : (
            <div style={styles.logoText}>{branding.company_name}</div>
          )}
        </div>

        <h2 style={styles.heading}>Two-factor authentication</h2>
        <p style={{ marginBottom: "1.25rem", color: "var(--color-text-secondary)", fontSize: ".875rem" }}>
          Enter the verification code from your authenticator app or request one by email.
        </p>

        {!emailSent && (
          <button
            type="button"
            className="btn btn-secondary"
            style={{ width: "100%", justifyContent: "center", marginBottom: "1rem" }}
            onClick={handleSend}
            disabled={loading}
          >
            Send code to my email
          </button>
        )}
        {emailSent && <div className="success-banner">Code sent to your email address.</div>}

        <form onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="mfa-code">Verification code</label>
            <input
              id="mfa-code"
              className="input"
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              maxLength={8}
              autoComplete="one-time-code"
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
              disabled={loading}
              autoFocus
              placeholder="6-digit code"
              required
            />
          </div>
          {error && (
            <div className="error-banner" role="alert" style={{ marginBottom: "1rem" }}>
              {error}
            </div>
          )}
          <button
            type="submit"
            className="btn btn-primary"
            style={{ width: "100%", justifyContent: "center", padding: ".65rem" }}
            disabled={loading || !code}
          >
            {loading ? <span className="loading-spinner" /> : "Verify"}
          </button>
        </form>
      </div>
      {branding.footer_text && (
        <p style={{ marginTop: "1.5rem", fontSize: ".75rem", color: "var(--color-text-secondary)", textAlign: "center" }}>
          {branding.footer_text}
        </p>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  page: {
    minHeight: "100dvh",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    padding: "1rem",
    background: "var(--color-bg)",
  },
  card: {
    background: "var(--color-surface)",
    borderRadius: "var(--radius-lg)",
    boxShadow: "var(--shadow-md)",
    padding: "2rem 2.25rem",
    width: "100%",
    maxWidth: "420px",
  },
  brandHeader: { textAlign: "center", marginBottom: "1.5rem" },
  logo: { maxHeight: "56px", maxWidth: "180px", objectFit: "contain" },
  logoText: { fontSize: "1.4rem", fontWeight: 700, color: "var(--brand-primary)" },
  heading: { fontSize: "1.125rem", fontWeight: 600, marginBottom: ".75rem", color: "var(--color-text)" },
};
