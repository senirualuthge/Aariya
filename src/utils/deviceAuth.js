// src/utils/deviceAuth.js
//
// Dashboard-side device identity (Patch 2/3).
//
// The long-lived device credential is obtained by redeeming a pairing code and
// is stored:
//   * in Electron, encrypted by the main process with safeStorage (Keychain /
//     DPAPI / libsecret). The renderer NEVER receives the credential: it asks
//     the main process to perform authenticated HTTP calls and to mint
//     one-use WebSocket tickets.
//   * in a direct browser dev session, in MEMORY ONLY — pairing is repeated
//     after a reload rather than silently persisting a credential in
//     localStorage.
//
// WebSockets never carry the credential: each connection asks
// `/api/auth/ws-ticket` for a single-use, path-bound ticket and offers it as
// the `aariya-ticket.<token>` subprotocol.

import { apiBase } from './apiHost.js';
import { authHeaders as legacyAuthHeaders } from './authToken.js';

const memory = { credential: null, loaded: false, loading: null };

export class DeviceAuthError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = 'DeviceAuthError';
    this.status = status;
  }
}

/**
 * The preload bridge exposes the credential broker, never the credential.
 * A browser dev session has no bridge and falls back to memory + direct fetch.
 */
function electronBridge() {
  if (typeof window === 'undefined') return null;
  const api = window.electronAPI;
  if (!api) return null;
  return api;
}

function hasBroker(api) {
  return Boolean(api && typeof api.authFetch === 'function');
}

function pairingRequired() {
  if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
    window.dispatchEvent(new CustomEvent('aariya:device-auth-required'));
  }
}

/**
 * Load a credential for browser-dev fetches.
 *
 * In Electron this always returns null: the credential stays inside the main
 * process and callers must use `personalFetch` instead of reading it.
 */
export async function loadCredential() {
  if (memory.loaded) return memory.credential;
  if (memory.loading) return memory.loading;

  memory.loading = (async () => {
    // No renderer-side read path exists in Electron by design.
    memory.credential = null;
    memory.loaded = true;
    memory.loading = null;
    return null;
  })();
  return memory.loading;
}

export async function hasCredential() {
  const api = electronBridge();
  if (api && typeof api.hasDeviceCredential === 'function') {
    try {
      return Boolean(await api.hasDeviceCredential());
    } catch {
      return false;
    }
  }
  return Boolean(await loadCredential());
}

/**
 * Ask the server whether it requires device authentication.
 *
 * The response deliberately exposes only the mode: no owner, device list or
 * pairing information.
 */
export async function getServerAuthMode() {
  const response = await fetch(
    `${apiBase()}/api/auth/mode`
  );

  if (!response.ok) {
    throw new DeviceAuthError(
      `Could not verify server authentication mode (${response.status})`,
      response.status,
    );
  }

  const body = await response.json();

  if (typeof body.device_auth_enabled !== "boolean") {
    throw new DeviceAuthError(
      "Invalid authentication-mode response"
    );
  }

  return body.device_auth_enabled;
}

/**
 * Persist the credential. Returns true when it was stored by Electron's
 * encrypted backend; a browser dev session keeps it in memory only.
 */
export async function storeCredential(credential) {
  const value = String(credential || '').trim();
  if (!value) return false;

  const api = electronBridge();
  if (api && typeof api.storeDeviceCredential === 'function') {
    try {
      if (await api.storeDeviceCredential(value)) {
        // Deliberately do not retain the plaintext in renderer memory.
        memory.credential = null;
        memory.loaded = true;
        return true;
      }
    } catch {
      /* fall through to memory only when there is no encrypted backend */
    }
    if (typeof api.authFetch === 'function') {
      // Encrypted storage is unavailable; do not silently degrade to memory.
      memory.credential = null;
      memory.loaded = true;
      return false;
    }
  }

  memory.credential = value;
  memory.loaded = true;
  return false;
}

export async function clearCredential() {
  memory.credential = null;
  memory.loaded = true;
  const api = electronBridge();
  if (api && typeof api.clearDeviceCredential === 'function') {
    try {
      await api.clearDeviceCredential();
    } catch {
      /* best effort */
    }
  }
}

/** Redeem a one-use pairing code created by the local CLI. */
export async function pairDevice({ pairingCode, label, platform }) {
  const response = await fetch(`${apiBase()}/api/auth/device/enroll`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      pairing_code: String(pairingCode || '').trim(),
      label: String(label || '').trim() || 'this computer',
      platform: String(platform || '').trim() || 'desktop',
    }),
  });

  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    throw new DeviceAuthError(body?.detail || 'Device pairing failed', response.status);
  }

  await storeCredential(body.credential);
  return body;
}

/** Authorization header for personal REST calls (empty when unpaired). */
export async function deviceAuthHeaders(extra = {}) {
  const credential = await loadCredential();
  if (!credential) return { ...extra };
  return { ...extra, Authorization: `Bearer ${credential}` };
}

/**
 * REST auth that prefers the paired device credential and otherwise keeps the
 * legacy shared token, so both deployment modes work during migration.
 *
 * Browser-dev only: Electron callers must use `personalFetch`, because the
 * credential is never exposed to the renderer.
 */
export async function personalAuthHeaders(extra = {}) {
  const headers = legacyAuthHeaders(extra);
  const credential = await loadCredential();
  if (credential) headers.Authorization = `Bearer ${credential}`;
  return headers;
}

async function handleAuthFailure(status) {
  if (status !== 401) return;
  await clearCredential();
  pairingRequired();
}

/**
 * Authenticated REST request.
 *
 * In Electron the main process attaches the credential after validating the
 * target origin; in a browser dev session the in-memory credential is used.
 */
export async function personalFetch(url, options = {}) {
  const api = electronBridge();
  if (hasBroker(api)) {
    const body = options.body == null
      ? null
      : (typeof options.body === 'string' ? options.body : JSON.stringify(options.body));

    let result;
    try {
      result = await api.authFetch({
        url: String(url),
        method: String(options.method || 'GET').toUpperCase(),
        headers: options.headers || {},
        body,
      });
    } catch (error) {
      throw new DeviceAuthError(
        `Desktop authentication bridge failed: ${error?.message || error}`,
        0,
      );
    }

    if (!result || typeof result.status !== 'number') {
      throw new DeviceAuthError('Desktop authentication bridge returned no response', 0);
    }
    if (result.status === 0) {
      throw new DeviceAuthError(
        result.error || 'Could not reach the Aariya backend',
        0,
      );
    }
    if (result.status === 401) await handleAuthFailure(401);

    // 204/205 responses must not carry a body, and the Response constructor
    // rejects one.
    const responseBody = result.status === 204 || result.status === 205
      ? null
      : (result.body ?? '');

    return new Response(responseBody, {
      status: result.status,
      headers: {
        'Content-Type': result.contentType || 'application/json',
      },
    });
  }

  const headers = await personalAuthHeaders(options.headers || {});
  return fetch(url, { ...options, headers });
}

/** Ask the backend for a single-use ticket for one WS path. */
export async function createWsTicket(path) {
  const api = electronBridge();
  if (api && typeof api.createWsTicket === 'function') {
    const result = await api.createWsTicket(path);
    if (result?.ok) return result.ticket;

    const status = typeof result?.status === 'number' ? result.status : 0;
    if (status === 401) await handleAuthFailure(401);
    throw new DeviceAuthError(
      result?.detail || 'Could not obtain a WebSocket ticket',
      status,
    );
  }

  const credential = await loadCredential();

  if (!credential) {
    const strictMode = await getServerAuthMode();

    if (strictMode) {
      pairingRequired();

      throw new DeviceAuthError(
        "Pair this computer before connecting to Aariya",
        401,
      );
    }

    return null;
  }

  const response = await fetch(`${apiBase()}/api/auth/ws-ticket`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${credential}`,
    },
    body: JSON.stringify({ path }),
  });

  if (!response.ok) {
    await handleAuthFailure(response.status);
    let detail = 'Could not obtain a WebSocket ticket';
    try {
      const body = await response.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new DeviceAuthError(detail, response.status);
  }
  const body = await response.json();
  return body.ticket;
}

/**
 * Open a private WebSocket with a fresh ticket subprotocol.
 *
 * With no credential, the server's mode decides: legacy mode opens the socket
 * unchanged, strict mode requires pairing first. Throws DeviceAuthError on a
 * refused ticket, which callers must treat as "pair again", not as a transient
 * failure to retry forever.
 */
export async function openAuthenticatedWebSocket(url, path) {
  const ticket = await createWsTicket(path);
  const socket = ticket
    ? new WebSocket(url, ['aariya.v1', `aariya-ticket.${ticket}`])
    : new WebSocket(url);
  watchForRevocation(socket);
  return socket;
}

/** Clear a revoked credential and stop callers from reconnecting forever. */
async function revokeLocally(socket) {
  await clearCredential();
  pairingRequired();
  try {
    socket.close(4001, 'Device revoked');
  } catch {
    /* already closed */
  }
}

function watchForRevocation(socket) {
  socket.addEventListener('message', (event) => {
    if (typeof event.data !== 'string') return;
    try {
      const frame = JSON.parse(event.data);
      if (frame && frame.type === 'device.revoked') revokeLocally(socket);
    } catch {
      /* non-JSON frames are handled by the socket owner */
    }
  });
}

/** Device identity for UI: null when unpaired (Electron or browser dev). */
export async function getDeviceIdentity() {
  if (!(await hasCredential())) return null;
  const response = await personalFetch(`${apiBase()}/api/auth/me`);
  if (!response.ok) {
    await handleAuthFailure(response.status);
    return null;
  }
  return response.json();
}

// Direct-browser development has no pairing UI yet: expose the same calls so
// `await aariyaDeviceAuth.pairDevice({pairingCode, label, platform})` works from
// the console, and remember that it is memory-only by design.
if (import.meta.env?.DEV && typeof window !== 'undefined') {
  window.aariyaDeviceAuth = {
    pairDevice,
    getDeviceIdentity,
    clearCredential,
  };
}
