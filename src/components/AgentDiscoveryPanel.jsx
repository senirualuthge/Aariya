// AgentDiscoveryPanel.jsx
// ──────────────────────────────────────────────────────────────────────────
// Drop-in panel for the Neural Swarm Dashboard.
// Shows newly discovered agents as glowing cards, with live connection
// status, detection-method badges, and a manual scan trigger.
//
// MobileGatewayAgent cards show inline live telemetry (clients, CPS,
// latency, uptime) fed from the brain_metrics WebSocket.
// ──────────────────────────────────────────────────────────────────────────

import { useState, useEffect, useRef } from "react";
import { useAgentRegistry } from "../hooks/useAgentRegistry";
import { subscribeMetrics } from "../systems/metricsClient";

// ── Live mobile telemetry hook ────────────────────────────────────────────
// Reads the same /ws/brain_metrics stream as the rest of the dashboard via the
// shared connection — no per-component socket needed.
function useMobileAgentsTelemetry() {
  const [telemetries, setTelemetries] = useState({});
  const unmounted = useRef(false);

  useEffect(() => {
    unmounted.current = false;
    const unsub = subscribeMetrics(
      (m) => m.type === "mobile_gateway_health" || m.type === "mobile_analytics_health" || m.type === "mobile_dashboard_health",
      (msg) => {
        if (unmounted.current) return;
        if (msg.data) {
          setTelemetries((prev) => ({
            ...prev,
            [msg.data.agent_id]: msg.data
          }));
        }
      }
    );

    return () => {
      unmounted.current = true;
      unsub();
    };
  }, []);

  return telemetries;
}

const DETECTION_COLORS = {
  inheritance: { bg: "#1a2a1a", border: "#2ecc71", text: "#2ecc71", label: "Inheritance" },
  folder:      { bg: "#1a1a2a", border: "#4a9eff", text: "#4a9eff", label: "Folder" },
  decorator:   { bg: "#2a1a2a", border: "#b44fff", text: "#b44fff", label: "Decorator" },
};

const STATUS_GLOW = {
  new:      "0 0 12px 2px rgba(255, 200, 0, 0.5)",
  existing: "none",
  removed:  "0 0 8px 2px rgba(255, 60, 60, 0.3)",
};

const STATUS_BORDER = {
  new:      "#ffc800",
  existing: "#2a2a3a",
  removed:  "#ff3c3c44",
};

export default function AgentDiscoveryPanel({ onAgentClick, className = "" }) {
  const { agents, stats, newAgents, isConnected, triggerScan, acknowledgeAll, acknowledge } =
    useAgentRegistry();
  const telemetries = useMobileAgentsTelemetry();

  const [filter, setFilter] = useState("all"); // "all" | "new" | "existing" | "removed"
  const [search, setSearch] = useState("");
  const [scanning, setScanning] = useState(false);
  const prevNewCount = useRef(0);
  const [flashNew, setFlashNew] = useState(false);

  // Flash the "NEW" counter when count increases
  useEffect(() => {
    if (newAgents.length > prevNewCount.current) {
      let t2;
      const t1 = setTimeout(() => {
        setFlashNew(true);
        t2 = setTimeout(() => setFlashNew(false), 1200);
      }, 0);
      prevNewCount.current = newAgents.length;
      return () => {
        clearTimeout(t1);
        if (t2) clearTimeout(t2);
      };
    }
    prevNewCount.current = newAgents.length;
  }, [newAgents.length]);

  const handleScan = async () => {
    setScanning(true);
    triggerScan();
    setTimeout(() => setScanning(false), 2000);
  };

  const filtered = agents.filter((a) => {
    if (filter !== "all" && a.status !== filter) return false;
    if (search && !a.name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div className={className} style={styles.panel}>
      {/* ── Header ── */}
      <div style={styles.header}>
        <div style={styles.headerLeft}>
          <span style={styles.title}>AGENT REGISTRY</span>
          <span style={{ ...styles.connDot, background: isConnected ? "#2ecc71" : "#ff4444" }} />
          <span style={styles.connLabel}>{isConnected ? "LIVE" : "OFFLINE"}</span>
        </div>
        <div style={styles.headerRight}>
          {newAgents.length > 0 && (
            <button
              style={styles.ackBtn}
              onClick={acknowledgeAll}
              title="Dismiss all new agent highlights"
            >
              ACK ALL
            </button>
          )}
          <button
            style={{ ...styles.scanBtn, opacity: scanning ? 0.6 : 1 }}
            onClick={handleScan}
            disabled={scanning}
          >
            {scanning ? "SCANNING…" : "⟳ SCAN"}
          </button>
        </div>
      </div>

      {/* ── Stats bar ── */}
      {stats && (
        <div style={styles.statsBar}>
          <StatChip label="TOTAL" value={stats.total} color="#4a9eff" />
          <StatChip
            label="NEW"
            value={stats.new}
            color="#ffc800"
            pulse={flashNew}
          />
          <StatChip label="REMOVED" value={stats.removed} color="#ff4444" />
          {stats.last_scan && (
            <span style={styles.lastScan}>
              {new Date(stats.last_scan).toLocaleTimeString()}
            </span>
          )}
        </div>
      )}

      {/* ── Filter + Search ── */}
      <div style={styles.controls}>
        <div style={styles.filterGroup}>
          {["all", "new", "existing", "removed"].map((f) => (
            <button
              key={f}
              style={{
                ...styles.filterBtn,
                background: filter === f ? "#1e2a3a" : "transparent",
                color: filter === f ? "#4a9eff" : "#556",
                borderColor: filter === f ? "#4a9eff44" : "transparent",
              }}
              onClick={() => setFilter(f)}
            >
              {f.toUpperCase()}
            </button>
          ))}
        </div>
        <input
          style={styles.searchInput}
          placeholder="Search agents…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* ── Agent list ── */}
      <div style={styles.list}>
        {filtered.length === 0 ? (
          <div style={styles.empty}>
            {agents.length === 0 ? "No agents discovered yet. Run a scan." : "No matches."}
          </div>
        ) : (
          filtered.map((agent) => (
            <AgentCard
              key={agent.id}
              agent={agent}
              mobileTelemetry={
                telemetries["mobile_gateway"] && agent.name === "MobileGatewayAgent" ? telemetries["mobile_gateway"] : 
                telemetries["mobile_analytics"] && agent.name === "MobileAnalyticsAgent" ? telemetries["mobile_analytics"] : 
                telemetries["mobile_dashboard"] && agent.name === "MobileDashboardAgent" ? telemetries["mobile_dashboard"] : null
              }
              onClick={() => {
                if (agent.status === "new") acknowledge(agent.id);
                onAgentClick?.(agent);
              }}
            />
          ))
        )}
      </div>
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────

function AgentCard({ agent, mobileTelemetry, onClick }) {
  const isNew = agent.status === "new";
  const isRemoved = agent.status === "removed";

  return (
    <div
      style={{
        ...styles.card,
        borderColor: STATUS_BORDER[agent.status] || "#2a2a3a",
        boxShadow: STATUS_GLOW[agent.status] || "none",
        opacity: isRemoved ? 0.45 : 1,
        cursor: "pointer",
      }}
      onClick={onClick}
    >
      {/* NEW badge */}
      {isNew && <span style={styles.newBadge}>NEW</span>}

      {/* Name + kind */}
      <div style={styles.cardTop}>
        <span style={styles.agentName}>{agent.name}</span>
        <span style={styles.kindPill}>{agent.kind?.toUpperCase()}</span>
      </div>

      {/* File path */}
      <div style={styles.filePath} title={agent.file}>
        {truncatePath(agent.file)}:{agent.line}
      </div>

      {/* Docstring */}
      {agent.docstring && (
        <div style={styles.docstring}>{agent.docstring}</div>
      )}

      {/* Telemetry Strip (Mobile panels only) */}
      {mobileTelemetry && (
        <div style={styles.telemetryStrip}>
          <div style={styles.telemetryItem}>
            <span style={styles.telemetryValue}>{mobileTelemetry.connected_clients}</span>
            <span style={styles.telemetryLabel}>DEVICES</span>
          </div>
          {mobileTelemetry.commands_per_second !== undefined ? (
            <div style={styles.telemetryItem}>
              <span style={{...styles.telemetryValue, color: "#ffc800"}}>{mobileTelemetry.commands_per_second?.toFixed(1) || 0}</span>
              <span style={styles.telemetryLabel}>CPS</span>
            </div>
          ) : (
            <div style={styles.telemetryItem}>
              <span style={{...styles.telemetryValue, color: "#ffc800"}}>{mobileTelemetry.payloads_per_second?.toFixed(1) || 0}</span>
              <span style={styles.telemetryLabel}>PPS</span>
            </div>
          )}
          <div style={styles.telemetryItem}>
            <span style={{...styles.telemetryValue, color: "#fc6e6e"}}>{mobileTelemetry.avg_latency_ms?.toFixed(0) || 0}ms</span>
            <span style={styles.telemetryLabel}>LATENCY</span>
          </div>
          <div style={styles.telemetryItem}>
            <span style={{...styles.telemetryValue, color: "#6efc8b"}}>{mobileTelemetry.uptime_seconds?.toFixed(0) || 0}s</span>
            <span style={styles.telemetryLabel}>UPTIME</span>
          </div>
        </div>
      )}

      {/* Detection badges */}
      <div style={styles.detectionRow}>
        {(Array.isArray(agent.detection) ? agent.detection : typeof agent.detection === 'string' ? [agent.detection] : []).map((d) => {
          const c = DETECTION_COLORS[d] || { bg: "#1a1a1a", border: "#444", text: "#888", label: d };
          return (
            <span
              key={d}
              style={{
                ...styles.detBadge,
                background: c.bg,
                border: `1px solid ${c.border}`,
                color: c.text,
              }}
            >
              {c.label}
            </span>
          );
        })}

        {/* Base classes */}
        {agent.base_classes?.slice(0, 2).map((b) => (
          <span key={b} style={styles.basePill}>↑ {b}</span>
        ))}
      </div>
    </div>
  );
}

function StatChip({ label, value, color, pulse }) {
  return (
    <div
      style={{
        ...styles.statChip,
        borderColor: `${color}44`,
        animation: pulse ? "pulseChip 0.6s ease 2" : "none",
      }}
    >
      <span style={{ color, fontSize: 15, fontWeight: 700, fontFamily: "monospace" }}>
        {value}
      </span>
      <span style={{ color: "#445", fontSize: 9, letterSpacing: 1 }}>{label}</span>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────

function truncatePath(path = "", max = 42) {
  if (!path || path.length <= max) return path;
  const parts = path.split("/");
  return "…/" + parts.slice(-2).join("/");
}

// ── Styles ────────────────────────────────────────────────────────────────

const styles = {
  panel: {
    background: "#0b0c14",
    border: "1px solid #1a1e2e",
    borderRadius: 8,
    display: "flex",
    flexDirection: "column",
    fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
    overflow: "hidden",
    minWidth: 320,
    maxWidth: 440,
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "10px 14px",
    borderBottom: "1px solid #1a1e2e",
    background: "#0d0f1a",
  },
  headerLeft: { display: "flex", alignItems: "center", gap: 8 },
  headerRight: { display: "flex", gap: 6 },
  title: { color: "#3a6fff", fontSize: 11, letterSpacing: 2, fontWeight: 700 },
  connDot: { width: 7, height: 7, borderRadius: "50%", display: "inline-block" },
  connLabel: { color: "#445", fontSize: 10, letterSpacing: 1 },
  scanBtn: {
    background: "#0f1a2a",
    border: "1px solid #1e3a5a",
    color: "#4a9eff",
    borderRadius: 4,
    padding: "3px 10px",
    fontSize: 10,
    letterSpacing: 1,
    cursor: "pointer",
  },
  ackBtn: {
    background: "#1a1600",
    border: "1px solid #ffc80044",
    color: "#ffc800",
    borderRadius: 4,
    padding: "3px 10px",
    fontSize: 10,
    letterSpacing: 1,
    cursor: "pointer",
  },
  statsBar: {
    display: "flex",
    gap: 8,
    padding: "8px 14px",
    borderBottom: "1px solid #12141f",
    alignItems: "center",
  },
  statChip: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    padding: "3px 10px",
    border: "1px solid",
    borderRadius: 4,
    background: "#0d0f18",
    minWidth: 46,
  },
  lastScan: { marginLeft: "auto", color: "#334", fontSize: 9, letterSpacing: 0.5 },
  controls: {
    display: "flex",
    padding: "8px 10px",
    gap: 8,
    borderBottom: "1px solid #12141f",
  },
  filterGroup: { display: "flex", gap: 2 },
  filterBtn: {
    border: "1px solid",
    borderRadius: 3,
    padding: "2px 7px",
    fontSize: 9,
    letterSpacing: 1,
    cursor: "pointer",
    transition: "all 0.15s",
  },
  searchInput: {
    flex: 1,
    background: "#0d0f18",
    border: "1px solid #1a1e2e",
    borderRadius: 4,
    color: "#8899bb",
    fontSize: 11,
    padding: "3px 8px",
    outline: "none",
    fontFamily: "inherit",
  },
  list: {
    flex: 1,
    overflowY: "auto",
    padding: "8px 10px",
    display: "flex",
    flexDirection: "column",
    gap: 6,
    maxHeight: 480,
  },
  empty: { color: "#334", fontSize: 11, textAlign: "center", padding: "20px 0" },
  card: {
    position: "relative",
    background: "#0d0f1a",
    border: "1px solid",
    borderRadius: 6,
    padding: "9px 11px 8px",
    transition: "border-color 0.2s, box-shadow 0.2s",
  },
  newBadge: {
    position: "absolute",
    top: -7,
    right: 10,
    background: "#ffc800",
    color: "#000",
    fontSize: 8,
    fontWeight: 700,
    letterSpacing: 1.5,
    padding: "1px 6px",
    borderRadius: 3,
  },
  cardTop: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 3 },
  agentName: { color: "#cce0ff", fontSize: 12, fontWeight: 600 },
  kindPill: {
    background: "#111a2a",
    color: "#445",
    fontSize: 8,
    letterSpacing: 1.5,
    padding: "2px 6px",
    borderRadius: 3,
  },
  filePath: { color: "#445", fontSize: 9, marginBottom: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  docstring: { color: "#556877", fontSize: 10, marginBottom: 5, fontStyle: "italic", lineHeight: 1.4 },
  detectionRow: { display: "flex", flexWrap: "wrap", gap: 4 },
  detBadge: { fontSize: 9, letterSpacing: 1, padding: "2px 7px", borderRadius: 3, fontWeight: 600 },
  basePill: { fontSize: 9, color: "#334", padding: "2px 6px", background: "#0a0c12", border: "1px solid #1a1e2e", borderRadius: 3 },
  telemetryStrip: {
    display: "flex",
    gap: 8,
    background: "#080910",
    border: "1px solid #1a2035",
    borderRadius: 4,
    padding: "6px 8px",
    marginBottom: 6,
    justifyContent: "space-between",
  },
  telemetryItem: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
  },
  telemetryValue: { color: "#4a9eff", fontSize: 11, fontWeight: 700, fontFamily: "monospace" },
  telemetryLabel: { color: "#445", fontSize: 8, letterSpacing: 0.5 },
};
