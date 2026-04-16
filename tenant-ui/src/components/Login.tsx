import React, { useEffect, useRef, useState } from "react";
import type { Branding } from "../lib/api";

interface Props {
  branding: Branding;
  loading: boolean;
  error: string | null;
  onLogin: (username: string, password: string, domain: string) => void;
}

export function Login({ branding, loading, error, onLogin }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [domain, setDomain] = useState("Default");
  const [failCount, setFailCount] = useState(0);
  const [cooldown, setCooldown] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Start cooldown after 3 consecutive failures
  useEffect(() => {
    if (failCount >= 3) {
      setCooldown(60);
      timerRef.current = setInterval(() => {
        setCooldown((c) => {
          if (c <= 1) {
            clearInterval(timerRef.current!);
            setFailCount(0);
            return 0;
          }
          return c - 1;
        });
      }, 1000);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [failCount]);

  // Track failed attempts
  useEffect(() => {
    if (error) setFailCount((c) => c + 1);
  }, [error]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (loading || cooldown > 0) return;
    onLogin(username.trim(), password, domain.trim() || "Default");
  };

  const isDisabled = loading || cooldown > 0;

  return (
    <div style={styles.page}>
      <div style={styles.card}>
        {/* Logo / company name */}
        <div style={styles.brandHeader}>
          {branding.logo_url ? (
            <img
              src={branding.logo_url}
              alt={branding.company_name}
              style={styles.logo}
            />
          ) : (
            <div style={styles.logoText}>{branding.company_name}</div>
          )}
          {branding.welcome_message && (
            <p style={styles.welcome}>{branding.welcome_message}</p>
          )}
        </div>

        <h2 style={styles.heading}>Sign in to your account</h2>

        <form onSubmit={handleSubmit} autoComplete="off">
          <div className="field">
            <label htmlFor="username">Username</label>
            <input
              id="username"
              className="input"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={isDisabled}
              autoFocus
              required
              aria-label="Username"
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isDisabled}
              required
              aria-label="Password"
            />
          </div>
          <div className="field">
            <label htmlFor="domain">Domain</label>
            <input
              id="domain"
              className="input"
              type="text"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              disabled={isDisabled}
              placeholder="Default"
              aria-label="Domain"
            />
          </div>

          {error && (
            <div className="error-banner" role="alert" style={{ marginBottom: "1rem" }}>
              Invalid credentials. Please try again.
            </div>
          )}
          {cooldown > 0 && (
            <div className="error-banner" role="alert" style={{ marginBottom: "1rem" }}>
              Too many attempts — please wait {cooldown}s
            </div>
          )}

          <button
            type="submit"
            className="btn btn-primary"
            style={{ width: "100%", justifyContent: "center", padding: ".65rem" }}
            disabled={isDisabled}
            aria-label="Sign in"
          >
            {loading ? <span className="loading-spinner" /> : "Sign in"}
          </button>
        </form>

        {/* Footer */}
        <div style={styles.footer}>
          {(branding.support_email || branding.support_url) && (
            <p>
              Need help?{" "}
              {branding.support_url ? (
                <a href={branding.support_url} target="_blank" rel="noopener noreferrer">
                  Contact support
                </a>
              ) : (
                <a href={`mailto:${branding.support_email}`}>{branding.support_email}</a>
              )}
            </p>
          )}
        </div>
      </div>

      {branding.footer_text && (
        <p style={styles.pageFooter}>{branding.footer_text}</p>
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
  brandHeader: {
    textAlign: "center",
    marginBottom: "1.5rem",
  },
  logo: {
    maxHeight: "56px",
    maxWidth: "180px",
    objectFit: "contain",
    marginBottom: ".5rem",
  },
  logoText: {
    fontSize: "1.4rem",
    fontWeight: 700,
    color: "var(--brand-primary)",
    marginBottom: ".25rem",
  },
  welcome: {
    fontSize: ".875rem",
    color: "var(--color-text-secondary)",
    marginTop: ".4rem",
  },
  heading: {
    fontSize: "1.125rem",
    fontWeight: 600,
    marginBottom: "1.25rem",
    color: "var(--color-text)",
  },
  footer: {
    marginTop: "1.25rem",
    textAlign: "center",
    fontSize: ".8125rem",
    color: "var(--color-text-secondary)",
  },
  pageFooter: {
    marginTop: "1.5rem",
    fontSize: ".75rem",
    color: "var(--color-text-secondary)",
    textAlign: "center",
  },
};
