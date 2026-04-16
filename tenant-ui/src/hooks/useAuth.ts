import { useState, useCallback, useEffect } from "react";
import {
  apiLogin,
  apiLogout,
  apiMe,
  apiMfaEmailSend,
  apiMfaVerify,
  setToken,
  clearToken,
  getToken,
  type LoginResponse,
  type MeResponse,
} from "../lib/api";

export type AuthState =
  | { phase: "unauthenticated" }
  | { phase: "mfa"; preauthToken: string; mfaMode: string }
  | { phase: "authenticated"; me: MeResponse };

export function useAuth() {
  const [state, setState] = useState<AuthState>(() => {
    // Restored sessions will refresh me data via useEffect below
    return getToken()
      ? { phase: "authenticated" as const, me: { username: "", keystone_user_id: "", projects: [], regions: [] } }
      : { phase: "unauthenticated" as const };
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // On mount: if a token was restored from sessionStorage, re-fetch me so
  // the Shell has the correct username / regions / projects.
  useEffect(() => {
    if (getToken()) {
      apiMe()
        .then((me) => setState({ phase: "authenticated", me }))
        .catch(() => {
          clearToken();
          setState({ phase: "unauthenticated" });
        });
    }
  }, []); // run once on mount

  const login = useCallback(async (username: string, password: string, domain: string) => {
    setLoading(true);
    setError(null);
    try {
      const resp: LoginResponse = await apiLogin(username, password, domain);
      if (resp.requires_mfa && resp.preauth_token) {
        setState({ phase: "mfa", preauthToken: resp.preauth_token, mfaMode: "code" });
      } else {
        setToken(resp.access_token, resp.expires_in);
        const me = await apiMe();
        setState({ phase: "authenticated", me });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }, []);

  const sendMfaEmail = useCallback(async (preauthToken: string) => {
    setLoading(true);
    setError(null);
    try {
      await apiMfaEmailSend(preauthToken);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send code");
    } finally {
      setLoading(false);
    }
  }, []);

  const verifyMfa = useCallback(
    async (preauthToken: string, code: string) => {
      setLoading(true);
      setError(null);
      try {
        const resp: LoginResponse = await apiMfaVerify(preauthToken, code);
        setToken(resp.access_token, resp.expires_in);
        const me = await apiMe();
        setState({ phase: "authenticated", me });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Invalid code");
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      clearToken();
      setState({ phase: "unauthenticated" });
    }
  }, []);

  return { state, loading, error, login, sendMfaEmail, verifyMfa, logout };
}
