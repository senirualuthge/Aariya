// src/utils/authToken.js
//
// Dashboard auth token for protected REST endpoints (System Health).
//
// Resolution order:
//   1. localStorage["aariya.auth.token"] — set at runtime, no rebuild needed
//   2. VITE_AARIYA_TOKEN / VITE_WS_TOKEN — build-time Vite env
//
// Returns "" when nothing is configured. Callers must then OMIT the
// Authorization header, so soft-mode deployments (loopback dev) keep working
// without a token.
//
// The server accepts the same token as the WebSocket layer:
// `Authorization: Bearer <WS_SECRET_TOKEN>` (or the dev allowlist tokens).

export const TOKEN_STORAGE_KEY = 'aariya.auth.token';

export function authToken() {
  try {
    if (typeof localStorage !== 'undefined' && localStorage) {
      const stored = localStorage.getItem(TOKEN_STORAGE_KEY);
      if (stored && stored.trim()) return stored.trim();
    }
  } catch {
    // Storage can be blocked (private mode / sandboxed renderer) — fall through.
  }
  const env = import.meta.env?.VITE_AARIYA_TOKEN
    || import.meta.env?.VITE_WS_TOKEN
    || '';
  return String(env).trim();
}

export function authHeaders(extra = {}) {
  const token = authToken();
  if (!token) return { ...extra };
  return { ...extra, Authorization: `Bearer ${token}` };
}

/**
 * Append the token as `?token=` for a WebSocket handshake.
 *
 * Browsers cannot set an Authorization header on `new WebSocket()`, so the
 * server's query-param path (the same one Flutter/Unity use) is the only
 * option. Returns the URL unchanged when no token is configured.
 */
export function wsUrlWithToken(url) {
  const token = authToken();
  if (!token) return url;
  try {
    const parsed = new URL(url);
    parsed.searchParams.set('token', token);
    return parsed.toString();
  } catch {
    const separator = url.includes('?') ? '&' : '?';
    return `${url}${separator}token=${encodeURIComponent(token)}`;
  }
}
