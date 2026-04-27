import { useState, useEffect } from "react";
import { apiBranding, type Branding } from "../lib/api";

const DEFAULTS: Branding = {
  company_name: "Cloud Portal",
  logo_url: null,
  favicon_url: null,
  primary_color: "#1976D2",
  accent_color: "#F29900",
  support_email: null,
  support_url: null,
  welcome_message: null,
  footer_text: null,
};

/**
 * Allow only relative paths and http/https URLs.
 * Blocks data:, javascript:, and any other scheme that could be used for
 * tracking pixels or script injection via <img src=...>.
 */
function sanitizeUrl(url: string | null): string | null {
  if (!url) return null;
  if (url.startsWith("/")) return url;
  try {
    const { protocol } = new URL(url);
    if (protocol === "https:" || protocol === "http:") return url;
  } catch {
    // not a valid absolute URL — reject
  }
  return null;
}

/**
 * Fetches branding from the tenant portal backend.
 *
 * @param projectId  Optional Keystone project UUID.  When supplied (after
 *                   login) the hook re-fetches to pick up per-tenant
 *                   overrides.  Falls back to the global CP branding if
 *                   no per-tenant row exists.
 */
export function useBranding(projectId?: string): Branding {
  const [branding, setBranding] = useState<Branding>(DEFAULTS);

  useEffect(() => {
    apiBranding(projectId)
      .then((b) => {
        const safe: Branding = {
          ...b,
          logo_url: sanitizeUrl(b.logo_url),
          favicon_url: sanitizeUrl(b.favicon_url),
        };
        setBranding(safe);
        applyBrandingToDom(safe);
      })
      .catch(() => {
        // Use defaults on error — the portal still loads
        applyBrandingToDom(DEFAULTS);
      });
  }, [projectId]);

  return branding;
}

function applyBrandingToDom(b: Branding): void {
  const root = document.documentElement;
  root.style.setProperty("--brand-primary", b.primary_color || DEFAULTS.primary_color);
  root.style.setProperty("--brand-accent", b.accent_color || DEFAULTS.accent_color);

  if (b.favicon_url) {
    const link = document.getElementById("favicon-link") as HTMLLinkElement | null;
    if (link) link.href = b.favicon_url;
  }

  if (b.company_name) {
    document.title = b.company_name;
  }
}
