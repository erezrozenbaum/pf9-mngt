/**
 * pf9-ui/src/lib/api.ts
 *
 * Shared fetch helpers for all API calls in the application.
 *
 * All components should import `getToken` / `apiFetch` from here instead of
 * reading `localStorage.getItem('auth_token')` inline. This eliminates the
 * duplicated token-extraction pattern (24 call-sites before this refactor)
 * and means future token-handling changes (e.g. moving to an httpOnly cookie)
 * require only one edit.
 *
 * Exports
 * -------
 * getToken()          : string | null
 *   Read the JWT from localStorage.  Returns null when not logged in.
 *
 * authHeaders()       : Record<string, string>
 *   Return `{ Authorization: 'Bearer ...' }` when a token is present, or `{}`
 *   when there is none.  Useful for callers that need to pass headers to a
 *   raw `fetch()` call alongside other custom options (e.g. streaming responses,
 *   file uploads with a non-JSON Content-Type).
 *
 * apiFetch<T>(path, opts?) : Promise<T>
 *   Thin fetch wrapper that:
 *     - prepends API_BASE to the path (empty string in production → relative URL)
 *     - injects the Authorization header automatically
 *     - sets Content-Type: application/json by default (caller-overridable)
 *     - throws an Error with the backend `detail` message (or a generic one)
 *       on any non-2xx response
 *     - parses and returns the JSON body
 *   The caller can override any header by passing `opts.headers`.
 */

import { API_BASE } from '../config';

/**
 * Returns a truthy value when the user has an active session, null otherwise.
 * The JWT is now stored exclusively in the httpOnly cookie and cannot be read
 * by JavaScript. We use the non-sensitive `token_expires_at` localStorage entry
 * as a session-active indicator for component guards (`if (!getToken()) return`).
 *
 * NOTE: The value returned is NOT a real JWT. It is used only as a boolean-ish
 * check. The actual credential sent to the server is the httpOnly cookie (via
 * `credentials: 'include'`) or a valid Bearer token for CI / external consumers.
 */
export function getToken(): string | null {
  const exp = localStorage.getItem('token_expires_at');
  if (!exp) return null;
  // Return null if session already expired so guards work correctly
  return new Date(exp).getTime() >= Date.now() ? exp : null;
}

/**
 * Build an Authorization header object.
 * Returns an empty object when there is no active session so callers can
 * safely spread it into a headers bag without conditional logic.
 */
export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * Fetch a JSON API endpoint with automatic auth injection.
 *
 * @param path   - Absolute path starting with '/', e.g. '/api/backup/status'.
 *                 `API_BASE` is prepended (empty string in production).
 * @param opts   - Standard `RequestInit` options.  `headers` values override
 *                 the defaults; when `opts.body` is a `FormData` instance the
 *                 `Content-Type` header is intentionally omitted so the browser
 *                 can add the correct `multipart/form-data; boundary=...` value.
 * @returns      Parsed JSON response body cast to T.
 * @throws       Error with the backend `detail` field or 'API error <status>'.
 */
export async function apiFetch<T>(path: string, opts?: RequestInit): Promise<T> {
  const token = getToken();
  const callerHeaders = (opts?.headers ?? {}) as Record<string, string>;
  const headers: Record<string, string> = {
    ...(opts?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...callerHeaders,
  };
  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers, credentials: 'include' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(err.detail ?? `API error ${res.status}`);
  }
  return res.json() as Promise<T>;
}
