// useAgentRegistry.js
// ─────────────────────
// React hook that connects to /ws/agents and keeps agent state in sync.
//
// Returns:
//   agents        — array of all active AgentRecord objects
//   stats         — { total, new, removed, by_detection, by_kind, last_scan }
//   newAgents     — agents with status === "new" (for badge/highlight)
//   isConnected   — WebSocket connection status
//   triggerScan   — fn() → manually trigger a backend scan
//   acknowledgeAll— fn() → mark all "new" agents as seen
//   acknowledge   — fn(id) → mark one agent as seen

import { useState, useEffect, useCallback } from "react";

const WS_URL = import.meta.env.VITE_AGENT_WS_URL || `ws://${window.location.hostname}:8000/api/agents/ws`;
const RECONNECT_DELAY_MS = 3000;
// If no ping arrives within this window, the connection is silently dead
const PING_WATCHDOG_MS = 60_000;

// ── Shared connection ─────────────────────────────────────────────────────────
// Several components (AgentDiscoveryPanel, AgentVisualizer) subscribe to the
// same agent registry. Rather than each opening its own /api/agents/ws socket
// (duplicate connections, duplicate pings, N× the broadcasts), a single
// module-level connection is shared, ref-counted across subscribers.
const listeners = new Set();
let sharedWs = null;
let sharedReconnectTimer = null;
let sharedWatchdogTimer = null;
let sharedRefCount = 0;

function dispatchToListeners(msg) {
  listeners.forEach((cb) => {
    try { cb(msg); } catch (e) { console.error("[useAgentRegistry] listener error", e); }
  });
}

function resetSharedWatchdog() {
  clearTimeout(sharedWatchdogTimer);
  sharedWatchdogTimer = setTimeout(() => {
    if (sharedWs) {
      console.warn("[useAgentRegistry] Ping watchdog expired — forcing reconnect");
      sharedWs.close();
    }
  }, PING_WATCHDOG_MS);
}

function connectShared() {
  if (sharedWs || sharedRefCount === 0) return;
  const ws = new WebSocket(WS_URL);
  sharedWs = ws;

  ws.onopen = () => {
    resetSharedWatchdog();
    dispatchToListeners({ type: "shared_open" });
  };

  ws.onmessage = (event) => {
    resetSharedWatchdog();
    try {
      dispatchToListeners(JSON.parse(event.data));
    } catch (e) {
      console.warn("[useAgentRegistry] Failed to parse message", e);
    }
  };

  ws.onclose = () => {
    clearTimeout(sharedWatchdogTimer);
    sharedWs = null;
    if (sharedRefCount > 0) {
      sharedReconnectTimer = setTimeout(connectShared, RECONNECT_DELAY_MS);
    }
  };

  ws.onerror = () => ws.close();
}

function disconnectShared() {
  sharedRefCount = Math.max(0, sharedRefCount - 1);
  if (sharedRefCount === 0) {
    clearTimeout(sharedReconnectTimer);
    clearTimeout(sharedWatchdogTimer);
    sharedWs?.close();
    sharedWs = null;
  }
}


export function useAgentRegistry() {
  const [agents, setAgents] = useState([]);
  const [stats, setStats] = useState(null);
  const [isConnected, setIsConnected] = useState(false);


  // ── Derived ──────────────────────────────────────────────────────────────
  const newAgents = agents.filter((a) => a.status === "new");

  // ── WebSocket setup (shared connection) ───────────────────────────────────
  const handleMessage = useCallback((msg) => {
    switch (msg.type) {
      case "agent_registry_snapshot":
        setAgents(msg.agents || []);
        if (msg.stats) setStats(msg.stats);
        break;

      case "agent_registry_update": {
        // Merge diff into current agents
        setAgents((prev) => {
          const map = new Map(prev.map((a) => [a.id, a]));

          // Apply new / updated
          for (const a of [...(msg.diff?.new || []), ...(msg.diff?.updated || [])]) {
            map.set(a.id, a);
          }

          // Apply removed
          for (const a of msg.diff?.removed || []) {
            const existing = map.get(a.id);
            if (existing) map.set(a.id, { ...existing, status: "removed" });
          }

          // Replace full list if provided (authoritative)
          if (msg.all_agents) {
            return msg.all_agents;
          }

          return Array.from(map.values());
        });
        if (msg.stats) setStats(msg.stats);
        break;
      }

      case "ack_all_done":
        setAgents((prev) =>
          prev.map((a) => (a.status === "new" ? { ...a, status: "existing" } : a))
        );
        break;

      case "ack_done":
        setAgents((prev) =>
          prev.map((a) =>
            a.id === msg.id ? { ...a, status: "existing" } : a
          )
        );
        break;

      case "ping":
        // Server keepalive — reply with pong so server can detect dead sockets
        if (sharedWs?.readyState === WebSocket.OPEN) {
          sharedWs.send(JSON.stringify({ action: "pong" }));
        }
        break;

      case "shared_open":
        setIsConnected(true);
        break;

      default:
        break;
    }
  }, []);

  useEffect(() => {
    const listener = (msg) => handleMessage(msg);
    listeners.add(listener);

    sharedRefCount += 1;
    connectShared();

    setIsConnected(!!sharedWs && sharedWs.readyState === WebSocket.OPEN);

    return () => {
      listeners.delete(listener);
      disconnectShared();
    };
  }, [handleMessage]);


  // ── Actions (send over the shared socket) ─────────────────────────────────
  const send = useCallback((msg) => {
    if (sharedWs?.readyState === WebSocket.OPEN) {
      sharedWs.send(JSON.stringify(msg));
    }
  }, []);

  const triggerScan = useCallback(() => send({ action: "scan" }), [send]);
  const acknowledgeAll = useCallback(() => send({ action: "ack_all" }), [send]);
  const acknowledge = useCallback((id) => send({ action: "ack", id }), [send]);

  return {
    agents,
    stats,
    newAgents,
    isConnected,
    triggerScan,
    acknowledgeAll,
    acknowledge,
  };
}
