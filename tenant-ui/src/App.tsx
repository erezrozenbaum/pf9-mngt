import { useState } from "react";
import { useBranding } from "./hooks/useBranding";
import { useAuth } from "./hooks/useAuth";
import { Login } from "./components/Login";
import { MfaStep } from "./components/MfaStep";
import { Shell } from "./components/Shell";

export type Screen =
  | "overview"
  | "dashboard"
  | "infrastructure"
  | "snapshots"
  | "monitoring"
  | "restore"
  | "runbooks"
  | "reports"
  | "chargeback"
  | "provision"
  | "activity";

export default function App() {
  const auth = useAuth();
  const [screen, setScreen] = useState<Screen>("overview");

  // After login, re-fetch branding scoped to the user's first project so
  // per-tenant colour/logo overrides are applied immediately.
  const projectId =
    auth.state.phase === "authenticated" && auth.state.me.projects.length > 0
      ? auth.state.me.projects[0].id
      : undefined;

  const branding = useBranding(projectId);

  if (auth.state.phase === "unauthenticated") {
    return (
      <Login
        branding={branding}
        loading={auth.loading}
        error={auth.error}
        onLogin={(u, p, d) => auth.login(u, p, d)}
      />
    );
  }

  if (auth.state.phase === "mfa") {
    const { preauthToken } = auth.state;
    return (
      <MfaStep
        branding={branding}
        preauthToken={preauthToken}
        loading={auth.loading}
        error={auth.error}
        onVerify={auth.verifyMfa}
        onSendEmail={auth.sendMfaEmail}
      />
    );
  }

  return (
    <Shell
      branding={branding}
      me={auth.state.me}
      screen={screen}
      onNavigate={setScreen}
      onLogout={auth.logout}
    />
  );
}
