import { useState } from "react";
import { useBranding } from "./hooks/useBranding";
import { useAuth } from "./hooks/useAuth";
import { Login } from "./components/Login";
import { MfaStep } from "./components/MfaStep";
import { Shell } from "./components/Shell";

export type Screen =
  | "dashboard"
  | "infrastructure"
  | "snapshots"
  | "monitoring"
  | "restore"
  | "runbooks"
  | "reports"
  | "provision"
  | "activity";

export default function App() {
  const branding = useBranding();
  const auth = useAuth();
  const [screen, setScreen] = useState<Screen>("dashboard");

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
