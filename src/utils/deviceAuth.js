// src/utils/deviceAuth.js
//
// Dashboard-side device identity (Patch 2/3).
//
// The long-lived device credential is obtained by redeeming a pairing code and
// is stored:
//   * in Electron, encrypted by the main process with safeStorage (Keychain /
//     DPAPI / libsecret) and reached through three narrow IPC calls;
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

function electronAuth() {
  if (typeof window === 'undefined') return null;
  const api = window.electronAPI;
  return api && typeof api.getDeviceCredential === 'function' ? api : null;
}

function pairingRequired() {
  if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
    window.dispatchEvent(new CustomEvent('aariya:device-auth-required'));
  }
}

/** Load the credential once, from Electron safe storage when available. */
export async function loadCredential() {
  if (memory.loaded) return memory.credential;
  if (memory.loading) return memory.loading;

  memory.loading = (async () => {
    let value = null;
    const api = electronAuth();
    if (api) {
      try {
        value = await api.getDeviceCredential();
      } catch {
        value = null;
      }
    }
    memory.credential = value || null;
    memory.loaded = true;
    memory.loading = null;
    return memory.credential;
  })();
  return memory.loading;
}

export async function hasCredential() {
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
  memory.credential = value;
  memory.loaded = true;

  const api = electronAuth();
  if (!api || typeof api.storeDeviceCredential !== 'function') return false;
  try {
    return Boolean(await api.storeDeviceCredential(value));
  } catch {
    return false;
  }
}

export async function clearCredential() {
  memory.credential = null;
  memory.loaded = true;
  const api = electronAuth();
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

/** Ask the backend for a single-use ticket for one WS path. */
export async function createWsTicket(path) {
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
  socket.addEventListener('close', (event) => {
    if (event.code === 4001) revokeLocally(socket);
  });
}

/** Current server-side identity, for a pairing/health panel. */
export async function getDeviceIdentity() {
  const credential = await loadCredential();
  if (!credential) return null;
  const response = await fetch(`${apiBase()}/api/auth/me`, {
    headers: { Authorization: `Bearer ${credential}` },
  });
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
