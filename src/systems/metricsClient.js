// src/systems/metricsClient.js
//
// Shared client for the /ws/brain_metrics endpoint.
//
// Several components consume the same metrics stream (event log / signals,
// emotion-predictor retrain events, mobile-agent health telemetry). Before this
// module, each opened its OWN socket to the same endpoint, so every broadcast
// was delivered N times per browser tab and the server juggled N connections
// per client. This module keeps ONE shared connection (ref-counted) and fans
// each message out to subscribers that match it.
import { eventBus } from '../core/EventBus';
import { apiWsBase } from '../utils/apiHost';
import { DeviceAuthError, openAuthenticatedWebSocket } from '../utils/deviceAuth';

const METRICS_WS_URL = `${apiWsBase()}/ws/brain_metrics`;
const RECONNECT_DELAY_MS = 4000;

// Every metrics message is also published on the shared bus, keyed by type.
export const METRICS_EVENT_PREFIX = 'metrics:';

const subscribers = new Set();          // { predicate: fn(msg) -> bool, handler: fn(msg) }
let sharedWs = null;
let reconnectTimer = null;
let refCount = 0;
let connecting = false;
// A rejected device credential is terminal until the user pairs again; do not
// hammer the server with reconnects every few seconds.
let authBlocked = false;

function dispatch(msg) {
  if (!msg || typeof msg !== 'object') return;
  eventBus.publish(`${METRICS_EVENT_PREFIX}${msg.type}`, msg);
  subscribers.forEach((s) => {
    try {
      if (s.predicate(msg)) s.handler(msg);
    } catch (e) {
      console.error('[metricsClient] subscriber error', e);
    }
  });
}

async function connect() {
  if (sharedWs || connecting || refCount === 0 || authBlocked) return;
  connecting = true;
  let ws;
  try {
    ws = await openAuthenticatedWebSocket(METRICS_WS_URL, '/ws/brain_metrics');
  } catch (err) {
    connecting = false;
    if (err instanceof DeviceAuthError) {
      authBlocked = true;
      console.warn('[metricsClient] device pairing required:', err.message);
      dispatch({ type: '__conn', connected: false, authRequired: true });
      return;
    }
    if (refCount > 0) reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
    return;
  }
  connecting = false;
  if (refCount === 0) {
    ws.close();
    return;
  }
  sharedWs = ws;
  ws.onopen = () => {
    dispatch({ type: '__conn', connected: true });
    ws.send(JSON.stringify({ type: 'ping' }));
  };

  ws.onmessage = (event) => {
    try {
      dispatch(JSON.parse(event.data));
    } catch { /* ignore */ }
  };

  ws.onclose = () => {
    dispatch({ type: '__conn', connected: false });
    sharedWs = null;
    if (refCount > 0 && !authBlocked) {
      reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
    }
  };
  ws.onerror = () => ws.close();
}

/** Offer a retry after the user pairs. */
export function resetMetricsAuth() {
  authBlocked = false;
  if (!sharedWs) connect();
}

/**
 * Subscribe to metrics messages matching a predicate.
 * @returns {Function} unsubscribe
 */
export function subscribeMetrics(predicate, handler) {
  const entry = { predicate, handler };
  subscribers.add(entry);
  refCount += 1;
  connect();
  return () => {
    subscribers.delete(entry);
    refCount = Math.max(0, refCount - 1);
    if (refCount === 0) {
      clearTimeout(reconnectTimer);
      sharedWs?.close();
      sharedWs = null;
    }
  };
}

/**
 * Send a JSON command frame over the shared /ws/brain_metrics socket.
 *
 * This is the laptop dashboard's AUTHORITY channel: the server executes
 * wipe_memory / set_personality / override_mode / force_mode here (they are
 * denied on the mobile channel) and replies with an `authority.ack` frame
 * that arrives through the same socket's onmessage → dispatch path.
 *
 * @param {string} action  e.g. 'wipe_memory' | 'set_personality' | 'override_mode' | 'force_mode'
 * @param {object} data    extra fields ({ preset, mode })
 * @returns {boolean} true if the frame was queued on an open socket
 */
export function sendMetricsCommand(action, data = {}) {
  if (!sharedWs || sharedWs.readyState !== WebSocket.OPEN) return false;
  sharedWs.send(JSON.stringify({ type: 'command', action, ...data }));
  return true;
}
