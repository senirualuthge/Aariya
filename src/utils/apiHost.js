// src/utils/apiHost.js
//
// Single source of truth for the backend host the UI talks to.
//
// The FastAPI server binds IPv4 (host="0.0.0.0"), but on many machines
// `localhost` resolves to IPv6 `::1` first — so `ws://localhost:8000` and
// `http://localhost:8000` fail to connect while `127.0.0.1` works. Map the
// loopback name to the numeric IPv4 address so the UI always reaches the
// server regardless of the browser's /etc/hosts resolution order.

export function apiHost() {
  // Node/test contexts have no window — fall back to the loopback default.
  if (typeof window === 'undefined' || !window.location) return '127.0.0.1';
  const host = window.location.hostname || 'localhost';
  if (host === 'localhost' || host === '::1') return '127.0.0.1';
  return host;
}

export function apiBase() {
  return `http://${apiHost()}:8000`;
}

export function apiWsBase() {
  return `ws://${apiHost()}:8000`;
}