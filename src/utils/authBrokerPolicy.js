// src/utils/authBrokerPolicy.js
//
// Pure policy helpers for the Electron main-process auth broker. Kept free of
// Electron imports so they can be unit-tested with plain Node.

export const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost', '[::1]', '::1']);

/**
 * A renderer may only ask the main process to send its credential to the
 * configured backend origin, or to a loopback host on the backend port.
 * This stops a compromised renderer from using the broker as an SSRF proxy.
 */
export function isAllowedBackendUrl(raw, backendOrigin, port = '8000') {
  try {
    const url = new URL(raw);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return false;
    if (url.origin === backendOrigin) return true;
    return url.port === port && LOOPBACK_HOSTS.has(url.hostname);
  } catch {
    return false;
  }
}

/**
 * The credential is attached by the main process only. Any Authorization
 * header supplied by renderer code is dropped so it cannot override it.
 */
export function stripRendererAuthorization(headers) {
  const clean = {};
  for (const [key, value] of Object.entries(headers || {})) {
    if (key.toLowerCase() === 'authorization') continue;
    clean[key] = value;
  }
  return clean;
}
