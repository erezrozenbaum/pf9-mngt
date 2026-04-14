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

export function useBranding(): Branding {
  const [branding, setBranding] = useState<Branding>(DEFAULTS);

  useEffect(() => {
    apiBranding()
      .then((b) => {
        setBranding(b);
        applyBrandingToDom(b);
      })
      .catch(() => {
        // Use defaults on error — the portal still loads
        applyBrandingToDom(DEFAULTS);
      });
  }, []);

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
