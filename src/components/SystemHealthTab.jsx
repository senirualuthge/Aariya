/**
 * SystemHealthTab.jsx — Aariya AI Control Center · System Health
 * ───────────────────────────────────────────────────────────────
 * A live panel for the Analytics Dashboard that shows:
 *   • Server performance  — CPU (overall + per-core), RAM, swap, disks,
 *                           network I/O, load average, process RSS / threads /
 *                           open files, uptime (server + system), platform.
 *   • System health checks — live probes for every core subsystem (brain, RAG,
 *                           memory, voice, predictor, planner, autonomy daemon,
 *                           swarm, meeting mode, security, prediction engine,
 *                           filesystem, desktop twin, self-heal, …). New probes
 *                           registered server-side appear automatically.
 *   • Functions (auto-discovered) — every function/agent the AgentScanner finds
 *                           in the codebase. Add a new function → it appears
 *                           here with a NEW badge, automatically.
 *   • Mobile app           — performance + health of connected Flutter app(s):
 *                           clients, command throughput, latency, payload
 *                           rates, uptime. Only shown while the app is live.
 *   • Device performance   — the client device running this dashboard: FPS,
 *                           JS heap, cores, memory, battery, network, screen,
 *                           WebGL renderer (measured locally in the browser).
 *
 * Data path: the server broadcasts `system_health` frames on the shared
 * /ws/brain_metrics socket every ~2 s (one connection, ref-counted). If no
 * frame arrives within a few seconds, this tab falls back to polling
 * GET /api/system/health so it never goes blind.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { subscribeMetrics } from '../systems/metricsClient';

// ── Status palette ────────────────────────────────────────────────────────────
const STATUS_COLOR = {
  ok:      '#10b981',
  warn:    '#ffd93d',
  down:    '#ef4444',
  crit:    '#ef4444',
  unknown: '#64748b',
  new:     '#00f2ff',
  existing:'#64748b',
  removed: '#ef4444',
};
const STATUS_LABEL = {
  ok: 'OK', warn: 'WARN', down: 'DOWN', crit: 'CRIT', unknown: '—',
};
const MONO = "'JetBrains Mono', monospace";

import { apiBase } from '../utils/apiHost';
const REST_URL = () => `${apiBase()}/api/system/health`;

// ── Hook: live health snapshot (WS frame + REST fallback) ────────────────────
function useSystemHealth() {
  const [snapshot, setSnapshot] = useState(null);
  const [source, setSource] = useState('offline'); // 'ws' | 'api' | 'offline' (label only)
  const [stale, setStale] = useState(true);        // true when both feeds are quiet
  const lastFrameAtRef = useRef(0);
  const inFlightRef = useRef(false);

  // Fallback fetch (stable across renders so the REFRESH button can call it).
  const fetchRestRef = useRef(null);

  useEffect(() => {
    let mounted = true;

    // Live path: server broadcasts a frame every ~2 s on the shared socket.
    const unsub = subscribeMetrics(
      (m) => m.type === 'system_health',
      (m) => {
        if (!mounted) return;
        lastFrameAtRef.current = Date.now();
        setStale(false);
        setSnapshot(m.data);
        setSource('ws');
      }
    );

    async function fetchRest() {
      if (inFlightRef.current || !mounted) return;
      inFlightRef.current = true;
      try {
        const res = await fetch(REST_URL());
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (mounted) {
          lastFrameAtRef.current = Date.now();
          setStale(false);
          setSnapshot(data);
          setSource('api');
        }
      } catch { /* offline — stay silent */ } finally {
        inFlightRef.current = false;
      }
    }
    fetchRestRef.current = fetchRest;

    fetchRest(); // immediate first paint
    const timer = setInterval(() => {
      const quietFor = Date.now() - lastFrameAtRef.current;
      if (quietFor > 6000) fetchRest();            // WS quiet → REST fallback
      setStale((prev) => {                          // both dead → honest offline
        const isStale = lastFrameAtRef.current === 0 || quietFor > 12000;
        return isStale === prev ? prev : isStale;
      });
    }, 3000);

    return () => { mounted = false; clearInterval(timer); unsub(); };
  }, []);

  return { snapshot, source, stale, refetch: () => fetchRestRef.current?.() };
}

// ── Hook: client device metrics (measured locally in this browser) ───────────
function useDeviceMetrics() {
  const [fps, setFps] = useState(0);
  const [heap, setHeap] = useState(null);       // { usedMb, totalMb }
  const [battery, setBattery] = useState(null); // { level, charging }
  const [net, setNet] = useState(null);         // { effectiveType, downlink, rtt, saveData }
  const framesRef = useRef(0);

  // FPS via requestAnimationFrame (1 s sampling window)
  useEffect(() => {
    let last = performance.now();
    let raf;
    const tick = (now) => {
      framesRef.current += 1;
      if (now - last >= 1000) {
        setFps(Math.round((framesRef.current * 1000) / (now - last)));
        framesRef.current = 0;
        last = now;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  // JS heap (Chromium only)
  useEffect(() => {
    const t = setInterval(() => {
      const m = performance?.memory;
      if (m && m.usedJSHeapSize) {
        setHeap({
          usedMb: Math.round(m.usedJSHeapSize / (1024 * 1024)),
          totalMb: Math.round(m.jsHeapSizeLimit / (1024 * 1024)),
        });
      }
    }, 2000);
    return () => clearInterval(t);
  }, []);

  // Battery + network (graceful when unavailable)
  useEffect(() => {
    let batteryObj = null;
    const updateBattery = () => setBattery({ level: batteryObj?.level ?? null, charging: batteryObj?.charging ?? null });
    const onLevel = () => updateBattery();
    const onCharge = () => updateBattery();
    try {
      if (navigator.getBattery) {
        navigator.getBattery().then((b) => {
          batteryObj = b;
          updateBattery();
          b.addEventListener('levelchange', onLevel);
          b.addEventListener('chargingchange', onCharge);
        }).catch(() => {});
      }
    } catch { /* ignore */ }

    const conn = navigator?.connection;
    const updateNet = () => {
      if (!conn) return;
      setNet({ effectiveType: conn.effectiveType, downlink: conn.downlink, rtt: conn.rtt, saveData: !!conn.saveData });
    };
    if (conn) {
      updateNet();
      conn.addEventListener('change', updateNet);
    }
    return () => {
      if (batteryObj) {
        batteryObj.removeEventListener('levelchange', onLevel);
        batteryObj.removeEventListener('chargingchange', onCharge);
      }
      if (conn) conn.removeEventListener('change', updateNet);
    };
  }, []);

  // Static device facts
  const facts = {
    cores: navigator.hardwareConcurrency ?? null,
    deviceMemory: navigator.deviceMemory ?? null,
    platform: (navigator.platform || navigator.userAgentData?.platform || 'unknown'),
    online: typeof navigator.onLine === 'boolean' ? navigator.onLine : true,
    screen: `${window.screen?.width || '?'}×${window.screen?.height || '?'} @${window.devicePixelRatio || 1}x`,
    webgl: (() => {
      try {
        const canvas = document.createElement('canvas');
        const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
        if (!gl) return null;
        const dbg = gl.getExtension('WEBGL_debug_renderer_info');
        const renderer = dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
        return String(renderer).slice(0, 48);
      } catch { return null; }
    })(),
  };

  return { fps, heap, battery, net, facts };
}

// ── Sparkline (tiny SVG trend) ───────────────────────────────────────────────
function Sparkline({ data, color = '#00f2ff', width = 120, height = 26 }) {
  if (!data || data.length < 2) {
    return <div style={{ width, height, color: 'rgba(255,255,255,0.2)', fontSize: 10, fontStyle: 'italic' }}>—</div>;
  }
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - 2 - ((v - min) / span) * (height - 4);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return (
    <svg width={width} height={height} style={{ display: 'block' }}>
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        style={{ filter: `drop-shadow(0 0 3px ${color}88)` }}
      />
      <circle
        cx={width} cy={height - 2 - ((data[data.length - 1] - min) / span) * (height - 4)}
        r={2.4} fill={color}
      />
    </svg>
  );
}

// ── Small building blocks ─────────────────────────────────────────────────────
function Panel({ title, icon, children, accent = '#00f2ff', right }) {
  return (
    <div className="stat-card" style={{ minWidth: 0 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ borderBottom: 'none', paddingBottom: 0, marginBottom: 4 }}>
          <span style={{ marginRight: 6 }}>{icon}</span>{title}
        </h2>
        {right}
      </div>
      <div style={{ borderBottom: `1px solid ${accent}22`, margin: '0 0 14px' }} />
      {children}
    </div>
  );
}

function Meter({ label, value, max = 100, color, display, hint }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const valColor = color || (pct > 90 ? '#ef4444' : pct > 75 ? '#ffd93d' : '#00f2ff');
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
        <span style={{ color: 'rgba(255,255,255,0.5)', letterSpacing: 0.5 }}>{label}</span>
        <span style={{ color: valColor, fontFamily: MONO, fontWeight: 700 }}>
          {display !== undefined ? display : `${Math.round(value)}%`}
          {hint ? <span style={{ color: 'rgba(255,255,255,0.3)', fontWeight: 400, marginLeft: 4 }}>{hint}</span> : null}
        </span>
      </div>
      <div style={{ height: 5, background: 'rgba(255,255,255,0.07)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{
          width: `${pct}%`, height: '100%', borderRadius: 3,
          background: valColor,
          transition: 'width 0.45s cubic-bezier(0.4,0,0.2,1)',
          boxShadow: `0 0 8px ${valColor}66`,
        }} />
      </div>
    </div>
  );
}

function Kv({ k, v, vColor }) {
  return (
    <div className="live-kv">
      <span className="key" style={{ textTransform: 'uppercase', fontSize: 10, letterSpacing: 1 }}>{k}</span>
      <span className="value" style={vColor ? { color: vColor } : undefined}>{v}</span>
    </div>
  );
}

function StatusDot({ status }) {
  const color = STATUS_COLOR[status] || '#64748b';
  const pulse = status === 'ok' || status === 'new';
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
      <span style={{
        width: 7, height: 7, borderRadius: '50%', background: color,
        boxShadow: `0 0 8px ${color}`, flexShrink: 0,
        animation: pulse ? 'statusPulse 1.6s infinite' : 'none',
      }} />
      <span style={{ color, fontSize: 10, fontWeight: 800, letterSpacing: 1 }}>{STATUS_LABEL[status] || status}</span>
    </span>
  );
}

function Chip({ children, color = '#64748b' }) {
  return (
    <span style={{
      padding: '2px 7px', borderRadius: 4, fontSize: 9, fontWeight: 700, letterSpacing: 0.5,
      background: `${color}1c`, color, border: `1px solid ${color}44`, whiteSpace: 'nowrap',
    }}>{children}</span>
  );
}

function fmtUptime(s) {
  s = Math.max(0, Math.floor(s || 0));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m ${s % 60}s`;
}

function fmtTime(ts) {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleTimeString();
}

// ── Main Tab ─────────────────────────────────────────────────────────────────
export default function SystemHealthTab() {
  const { snapshot, source, stale, refetch } = useSystemHealth();
  const dev = useDeviceMetrics();

  const server = snapshot?.server || {};
  const checks = snapshot?.checks || [];
  const functions = snapshot?.functions || [];
  const mobile = snapshot?.mobile || {};
  const history = snapshot?.history || {};
  const score = snapshot?.score ?? null;

  const serverOnline = !stale && snapshot != null;
  const mobileConnected = !!mobile.connected;
  const cpu = server.cpu_percent ?? null;
  const ram = server.ram_percent ?? null;
  const downChecks = checks.filter((c) => c.status === 'down' || c.status === 'crit');
  const warnChecks = checks.filter((c) => c.status === 'warn');
  const okChecks = checks.filter((c) => c.status === 'ok');
  const newFuncs = functions.filter((f) => f.status === 'new').length;

  const scoreColor = score === null ? '#64748b' : score >= 85 ? '#10b981' : score >= 65 ? '#ffd93d' : '#ef4444';

  const cpuColor = cpu === null ? null : cpu > 90 ? '#ef4444' : cpu > 75 ? '#ffd93d' : '#00f2ff';
  const ramColor = ram === null ? null : ram > 90 ? '#ef4444' : ram > 75 ? '#ffd93d' : '#00f2ff';
  const devFpsColor = dev.fps === 0 ? '#64748b' : dev.fps >= 45 ? '#10b981' : dev.fps >= 25 ? '#ffd93d' : '#ef4444';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>

      {/* ── KPI row ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
        <KpiCard
          icon="🛡️" label="Health Score" value={score === null ? '—' : `${score}/100`}
          color={scoreColor} sub={snapshot ? `updated ${source === 'ws' ? 'live' : 'via REST'}` : 'waiting for first frame'}
        />
        <KpiCard
          icon={serverOnline ? '🟢' : '🔴'} label="Server" value={serverOnline ? 'ONLINE' : 'OFFLINE'}
          color={serverOnline ? '#10b981' : '#ef4444'}
          sub={snapshot ? `${fmtUptime(server.server_uptime_s)} uptime · ${snapshot.collection_ms ?? '?'}ms collect` : 'no data yet'}
        />
        <KpiCard
          icon={mobileConnected ? '📱' : '📴'} label="Mobile App"
          value={mobileConnected ? `${mobile.clients} connected` : 'OFFLINE'}
          color={mobileConnected ? '#a78bfa' : '#64748b'}
          sub={mobileConnected ? `peak ${mobile.peak_clients} · ${mobile.avg_latency_ms ?? '?'}ms avg latency` : 'appears when the app connects'}
        />
        <KpiCard
          icon="⚡" label="Device FPS" value={dev.fps > 0 ? `${dev.fps}` : '—'}
          color={devFpsColor} sub="this browser's render rate"
        />
      </div>

      {/* ── GEV Health ── */}
      <GevHealthPanel apiBase={apiBase} />

      {/* ── Row: Server performance + Device performance ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16, alignItems: 'start' }}>
        {/* Server performance */}
        <Panel
          title="Server Performance"
          icon="🖥️"
          right={
            <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
              {history.cpu?.length > 1 && (
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 8, color: 'rgba(255,255,255,0.3)', letterSpacing: 1, marginBottom: 2 }}>CPU TREND</div>
                  <Sparkline data={history.cpu} color={cpuColor || '#00f2ff'} />
                </div>
              )}
              {history.ram?.length > 1 && (
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 8, color: 'rgba(255,255,255,0.3)', letterSpacing: 1, marginBottom: 2 }}>RAM TREND</div>
                  <Sparkline data={history.ram} color="#ff8fa3" />
                </div>
              )}
            </div>
          }
        >
          {serverOnline ? (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 28px' }}>
                <div>
                  <Meter label="CPU" value={cpu ?? 0} max={100} color={cpuColor} display={cpu === null ? 'n/a' : `${cpu}%`} />
                  {server.cpu_per_core?.length > 0 && (
                    <div style={{ display: 'flex', gap: 3, marginBottom: 12, flexWrap: 'wrap' }}>
                      {server.cpu_per_core.map((c, i) => (
                        <div key={i} style={{ flex: 1, minWidth: 12, textAlign: 'center' }}>
                          <div style={{ height: 26, background: 'rgba(255,255,255,0.05)', borderRadius: 3, position: 'relative', overflow: 'hidden' }}>
                            <div style={{
                              position: 'absolute', bottom: 0, left: 0, right: 0,
                              height: `${Math.min(100, c)}%`,
                              background: c > 90 ? '#ef4444' : c > 75 ? '#ffd93d' : '#00f2ff',
                              opacity: 0.85, transition: 'height 0.4s ease',
                            }} />
                          </div>
                          <div style={{ fontSize: 7, color: 'rgba(255,255,255,0.3)', marginTop: 2 }}>{i + 1}</div>
                        </div>
                      ))}
                    </div>
                  )}
                  <Meter label="RAM" value={ram ?? 0} max={100} color={ramColor}
                    display={ram === null ? 'n/a' : `${ram}% · ${server.ram_used_gb ?? '?'}/${server.ram_total_gb ?? '?'} GB`} />
                  {server.swap_percent !== undefined && (
                    <Meter label="Swap" value={server.swap_percent} max={100} display={`${server.swap_percent}%`} />
                  )}
                  {Array.isArray(server.disks) && server.disks.length > 0 && server.disks.slice(0, 3).map((d) => (
                    <Meter key={d.mount} label={`Disk ${d.mount}`} value={d.percent} max={100}
                      display={`${d.percent}% · ${d.used_gb}/${d.total_gb} GB`}
                      color={d.percent > 90 ? '#ef4444' : d.percent > 80 ? '#ffd93d' : '#34d399'} />
                  ))}
                </div>
                <div>
                  <Kv k="Server uptime" v={fmtUptime(server.server_uptime_s)} />
                  <Kv k="System uptime" v={fmtUptime(server.system_uptime_s)} />
                  <Kv k="Load average" v={server.load_avg ? server.load_avg.map((x) => x.toFixed(2)).join(' / ') : '—'} />
                  <Kv k="Process RSS" v={server.process?.rss_mb != null ? `${server.process.rss_mb} MB` : '—'} />
                  <Kv k="Threads" v={server.process?.threads ?? '—'} />
                  <Kv k="Open files" v={server.process?.open_files ?? '—'} />
                  <Kv k="Process CPU" v={server.process?.cpu_percent != null ? `${server.process.cpu_percent}%` : '—'} />
                  <Kv k="Python" v={server.process?.python ?? '—'} />
                  <Kv k="Platform" v={server.platform || '—'} />
                  <Kv k="Hostname" v={server.hostname || '—'} />
                  {server.network && (
                    <>
                      <Kv k="Net ↑ / ↓" v={`${server.network.bytes_sent_mb ?? 0} / ${server.network.bytes_recv_mb ?? 0} MB`} />
                      <Kv k="Net connections" v={server.network.connections ?? '—'} />
                    </>
                  )}
                </div>
              </div>
            </>
          ) : (
            <EmptyState icon="🛰️" text="Server unreachable — waiting for the backend to come online." />
          )}
        </Panel>

        {/* Device performance (this client) */}
        <Panel title="Device Performance" icon="💻" accent="#ff8fa3">
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 14 }}>
            <div style={{
              width: 74, height: 74, borderRadius: '50%', position: 'relative', flexShrink: 0,
              background: `conic-gradient(${devFpsColor} ${Math.min(100, (dev.fps / 60) * 100) * 3.6}deg, rgba(255,255,255,0.06) 0deg)`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: `0 0 18px ${devFpsColor}44`,
            }}>
              <div style={{
                width: 58, height: 58, borderRadius: '50%', background: '#141a2b',
                display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
              }}>
                <span style={{ fontSize: 16, fontWeight: 800, color: devFpsColor, fontFamily: MONO }}>{dev.fps || '—'}</span>
                <span style={{ fontSize: 8, color: 'rgba(255,255,255,0.4)', letterSpacing: 1 }}>FPS</span>
              </div>
            </div>
            <div style={{ flex: 1 }}>
              <Kv k="CPU cores" v={dev.facts.cores ?? '—'} />
              <Kv k="Device memory" v={dev.facts.deviceMemory ? `${dev.facts.deviceMemory} GB` : '—'} />
              <Kv k="Screen" v={dev.facts.screen} />
              <Kv k="Online" v={dev.facts.online ? 'yes' : 'no'} vColor={dev.facts.online ? '#10b981' : '#ef4444'} />
            </div>
          </div>

          {dev.heap && (
            <Meter label="JS Heap" value={dev.heap.usedMb} max={Math.max(1, dev.heap.totalMb)}
              display={`${dev.heap.usedMb} / ${dev.heap.totalMb} MB`} color="#a78bfa" />
          )}
          {dev.battery?.level != null && (
            <Meter label="Battery" value={dev.battery.level * 100} max={100}
              display={`${Math.round(dev.battery.level * 100)}% ${dev.battery.charging ? '⚡ charging' : ''}`}
              color="#34d399" />
          )}
          {dev.net && (
            <>
              <Kv k="Network" v={`${dev.net.effectiveType} · ${dev.net.downlink} Mbps`} />
              <Kv k="RTT" v={dev.net.rtt != null ? `${dev.net.rtt} ms` : '—'} />
              {dev.net.saveData && <div style={{ fontSize: 10, color: '#ffd93d', marginTop: 4 }}>⚠ data-saver mode on</div>}
            </>
          )}
          <div style={{ borderTop: '1px solid rgba(255,255,255,0.05)', marginTop: 12, paddingTop: 10 }}>
            <Kv k="Platform" v={dev.facts.platform} />
            <Kv k="GPU / Renderer" v={dev.facts.webgl || 'not detected'} />
          </div>
        </Panel>
      </div>

      {/* ── Row: System health checks + Mobile app ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16, alignItems: 'start' }}>
        {/* System health checks */}
        <Panel
          title="System Health"
          icon="🫀"
          accent={downChecks.length ? '#ef4444' : warnChecks.length ? '#ffd93d' : '#10b981'}
          right={
            <div style={{ display: 'flex', gap: 8 }}>
              <Chip color="#10b981">{okChecks.length} ok</Chip>
              {warnChecks.length > 0 && <Chip color="#ffd93d">{warnChecks.length} warn</Chip>}
              {downChecks.length > 0 && <Chip color="#ef4444">{downChecks.length} down</Chip>}
            </div>
          }
        >
          {checks.length === 0 ? (
            <EmptyState icon="🔌" text="No health checks yet — the monitor broadcasts as soon as the server is reachable." />
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              {checks.map((c) => {
                const st = c.status || 'unknown';
                const color = STATUS_COLOR[st];
                return (
                  <div key={c.name} style={{
                    display: 'flex', alignItems: 'center', gap: 10,
                    padding: '9px 12px', borderRadius: 8,
                    background: 'rgba(255,255,255,0.02)',
                    border: '1px solid rgba(255,255,255,0.05)',
                    borderLeft: `3px solid ${color}`,
                    transition: 'all 0.2s',
                  }}
                    onMouseOver={(e) => { e.currentTarget.style.background = `${color}10`; e.currentTarget.style.borderColor = `${color}44`; }}
                    onMouseOut={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.02)'; e.currentTarget.style.borderColor = 'rgba(255,255,255,0.05)'; }}
                  >
                    <StatusDot status={st} />
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: '#e2e8f0', letterSpacing: 0.5 }}>{c.label || c.name}</div>
                      <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.detail || '—'}</div>
                    </div>
                    {c.latency_ms != null && (
                      <span style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', fontFamily: MONO, flexShrink: 0 }}>{c.latency_ms.toFixed(1)}ms</span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </Panel>

        {/* Mobile app */}
        <Panel
          title="Mobile App"
          icon="📱"
          accent={mobileConnected ? '#a78bfa' : '#64748b'}
          right={<Chip color={mobileConnected ? '#10b981' : '#64748b'}>{mobileConnected ? 'CONNECTED' : 'NOT CONNECTED'}</Chip>}
        >
          {mobileConnected ? (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
                <span style={{
                  width: 10, height: 10, borderRadius: '50%', background: '#a78bfa', flexShrink: 0,
                  boxShadow: '0 0 12px #a78bfa', animation: 'statusPulse 1.6s infinite',
                }} />
                <div>
                  <div style={{ fontSize: 20, fontWeight: 800, color: '#a78bfa', fontFamily: MONO }}>{mobile.clients}</div>
                  <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.4)', letterSpacing: 1, textTransform: 'uppercase' }}>active client{+mobile.clients === 1 ? '' : 's'}</div>
                </div>
                {history.mobile_clients?.length > 1 && (
                  <div style={{ marginLeft: 'auto' }}>
                    <div style={{ fontSize: 8, color: 'rgba(255,255,255,0.3)', letterSpacing: 1, marginBottom: 2 }}>CLIENTS</div>
                    <Sparkline data={history.mobile_clients} color="#a78bfa" width={80} height={22} />
                  </div>
                )}
              </div>
              <Kv k="Peak clients" v={mobile.peak_clients ?? 0} />
              <Kv k="Commands processed" v={mobile.commands_processed ?? 0} />
              <Kv k="Commands / sec" v={mobile.commands_per_second ?? 0} />
              <Kv k="Avg latency" v={mobile.avg_latency_ms != null ? `${mobile.avg_latency_ms} ms` : '—'} />
              <Kv k="Interrupts" v={mobile.interrupts_sent ?? 0} />
              <Kv k="Remote inputs" v={mobile.remote_inputs_forwarded ?? 0} />
              <Kv k="Uptime" v={fmtUptime(mobile.uptime_s)} />
              <Kv k="Last activity" v={fmtTime(mobile.last_activity_ts)} />
              {mobile.channels?.analytics && (
                <Kv k="Analytics stream" v={`${mobile.channels.analytics.payloads_sent ?? 0} payloads · ${mobile.channels.analytics.payloads_per_second ?? 0}/s`} />
              )}
              {mobile.channels?.dashboard && (
                <Kv k="Dashboard stream" v={`${mobile.channels.dashboard.payloads_sent ?? 0} payloads · ${mobile.channels.dashboard.payloads_per_second ?? 0}/s`} />
              )}

              {/* ── Phone-reported device metrics (battery / CPU / memory) ── */}
              {mobile.device && Object.keys(mobile.device).length > 0 && (
                <div style={{ borderTop: '1px solid rgba(167,139,250,0.15)', marginTop: 12, paddingTop: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                    <span style={{ fontSize: 9, color: 'rgba(255,255,255,0.35)', letterSpacing: 1.5, textTransform: 'uppercase' }}>
                      📲 Phone Device
                    </span>
                    {mobile.device_last_ts != null && (
                      <span style={{ fontSize: 9, color: 'rgba(255,255,255,0.25)', fontFamily: MONO }}>
                        {fmtTime(mobile.device_last_ts)}
                      </span>
                    )}
                  </div>
                  {mobile.device.battery != null && (
                    <Meter label="Battery" value={mobile.device.battery} max={100}
                      display={`${mobile.device.battery}%${mobile.device.charging ? ' ⚡' : ''}`}
                      color={mobile.device.battery > 20 ? '#34d399' : '#ef4444'} />
                  )}
                  {mobile.device.cpu_percent != null && (
                    <Meter label="CPU" value={mobile.device.cpu_percent} max={100}
                      display={`${mobile.device.cpu_percent}%`}
                      color={mobile.device.cpu_percent > 85 ? '#ef4444' : mobile.device.cpu_percent > 65 ? '#ffd93d' : '#a78bfa'} />
                  )}
                  {mobile.device.ram_percent != null && (
                    <Meter label="Memory" value={mobile.device.ram_percent} max={100}
                      display={`${mobile.device.ram_percent}% · ${mobile.device.ram_used_gb ?? '?'}/${mobile.device.ram_total_gb ?? '?'} GB`}
                      color="#fb923c" />
                  )}
                  <Kv k="Model" v={[mobile.device.manufacturer, mobile.device.model].filter(Boolean).join(' ') || '—'} />
                  <Kv k="OS" v={mobile.device.os_version || mobile.device.platform || '—'} />
                </div>
              )}
            </>
          ) : (
            <EmptyState icon="📴" text="No mobile app connected. The performance panel appears here the moment the Flutter app links to this server." />
          )}
        </Panel>
      </div>

      {/* ── Auto-discovered functions ── */}
      <Panel
        title="Functions (auto-discovered)"
        icon="🧩"
        accent={newFuncs > 0 ? '#00f2ff' : '#6bcbef'}
        right={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Chip color="#6bcbef">{functions.length} functions</Chip>
            {newFuncs > 0 && <Chip color="#00f2ff">{newFuncs} NEW</Chip>}
            <button
              onClick={() => refetch()}
              style={{
                background: 'rgba(0,242,255,0.06)', border: '1px solid rgba(0,242,255,0.2)',
                color: '#00f2ff', borderRadius: 6, padding: '3px 10px', cursor: 'pointer',
                fontSize: 10, fontWeight: 700, letterSpacing: 1, transition: 'all 0.2s',
              }}
              onMouseOver={(e) => { e.currentTarget.style.background = 'rgba(0,242,255,0.16)'; }}
              onMouseOut={(e) => { e.currentTarget.style.background = 'rgba(0,242,255,0.06)'; }}
            >⟳ REFRESH</button>
          </div>
        }
      >
        <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)', marginBottom: 12, lineHeight: 1.5 }}>
          Every function/agent the scanner finds in the codebase appears here automatically — add new code and it shows up with a <span style={{ color: '#00f2ff', fontWeight: 700 }}>NEW</span> badge.
        </div>
        {functions.length === 0 ? (
          <EmptyState icon="🧩" text="No functions discovered yet — the scanner feeds the registry on server start." />
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 10 }}>
            {functions.map((f) => {
              const st = f.status || 'existing';
              const color = STATUS_COLOR[st];
              return (
                <div key={`${f.name}-${f.file}`} style={{
                  background: 'rgba(255,255,255,0.02)', border: `1px solid ${st === 'new' ? '#00f2ff44' : 'rgba(255,255,255,0.06)'}`,
                  borderRadius: 10, padding: '12px 14px',
                  boxShadow: st === 'new' ? '0 0 14px rgba(0,242,255,0.12)' : 'none',
                  transition: 'all 0.2s',
                }}
                  onMouseOver={(e) => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.borderColor = `${color}66`; }}
                  onMouseOut={(e) => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.borderColor = st === 'new' ? '#00f2ff44' : 'rgba(255,255,255,0.06)'; }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8, marginBottom: 6 }}>
                    <span style={{ fontSize: 12, fontWeight: 700, color: '#e2e8f0' }}>{f.display_name || f.name}</span>
                    {st === 'new' && (
                      <span style={{
                        fontSize: 8, fontWeight: 900, letterSpacing: 1, color: '#00f2ff', padding: '1px 6px', borderRadius: 4,
                        background: 'rgba(0,242,255,0.12)', border: '1px solid rgba(0,242,255,0.4)',
                        animation: 'statusPulse 1.4s infinite',
                      }}>NEW</span>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 6 }}>
                    <Chip color={st === 'new' ? '#00f2ff' : st === 'removed' ? '#ef4444' : '#64748b'}>{st.toUpperCase()}</Chip>
                    <Chip color="#6bcbef">{f.kind || 'class'}</Chip>
                    {(Array.isArray(f.detection) ? f.detection : typeof f.detection === 'string' ? [f.detection] : []).slice(0, 2).map((d) => <Chip key={d} color="#94a3b8">{d}</Chip>)}
                  </div>
                  <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', fontFamily: MONO, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={f.file}>{f.file || '—'}</div>
                  <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.2)', marginTop: 2 }}>first seen {f.first_seen ? new Date(f.first_seen).toLocaleDateString() : '—'}</div>
                </div>
              );
            })}
          </div>
        )}
      </Panel>
    </div>
  );
}

// ── KPI card ──────────────────────────────────────────────────────────────────
function KpiCard({ icon, label, value, color, sub }) {
  return (
    <div className="stat-card" style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 22, marginBottom: 6 }}>{icon}</div>
      <div style={{ fontSize: 24, fontWeight: 800, color, fontFamily: MONO, marginBottom: 3, letterSpacing: 0.5 }}>{value}</div>
      <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.45)', textTransform: 'uppercase', letterSpacing: 1.2, fontWeight: 700 }}>{label}</div>
      {sub && <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.28)', marginTop: 6 }}>{sub}</div>}
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────
function EmptyState({ icon, text }) {
  return (
    <div style={{
      textAlign: 'center', padding: '34px 10px', color: 'rgba(255,255,255,0.25)',
      fontStyle: 'italic', fontSize: 12, lineHeight: 1.6,
    }}>
      <div style={{ fontSize: 26, marginBottom: 8 }}>{icon}</div>
      {text}
    </div>
  );
}

// ── GEV Health Panel ────────────────────────────────────────────────────────
function GevHealthPanel({ apiBase }) {
  const [status, setStatus] = useState(null); // { age_s, live_layers, total_layers, mode }
  const [refreshing, setRefreshing] = useState(false);
  const [lastRefreshTs, setLastRefreshTs] = useState(null);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/api/system/health`);
      if (!res.ok) return;
      const data = await res.json();
      const gevCheck = (data.checks || []).find((c) => c.name === 'gev');
      if (gevCheck) setStatus(gevCheck.meta || {});
    } catch { /* offline */ }
  }, [apiBase]);

  useEffect(() => {
    fetchStatus();
    const t = setInterval(fetchStatus, 6000);
    return () => clearInterval(t);
  }, [fetchStatus]);

  const doRefresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    try {
      const res = await fetch(`${apiBase}/api/gev/manual-refresh`, { method: 'POST' });
      if (res.ok) {
        setLastRefreshTs(Date.now());
        // Re-fetch status after refresh
        setTimeout(fetchStatus, 1500);
      }
    } catch { /* ignore */ }
    setRefreshing(false);
  };

  const age = status?.age_s;
  const liveLayers = status?.live_layers ?? 0;
  const totalLayers = status?.total_layers ?? 0;
  const mode = status?.mode || 'unknown';
  const hasData = liveLayers > 0;
  const isStale = age != null && age > 300;

  const statusColor = !hasData ? '#64748b' : isStale ? '#ffd93d' : '#10b981';
  const ageLabel = age != null ? (age < 60 ? `${Math.round(age)}s ago` : `${Math.round(age / 60)}m ago`) : 'never';

  return (
    <Panel
      title="GEV (God's Eye View)"
      icon="🌍"
      accent={statusColor}
      right={
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Chip color={statusColor}>{hasData ? `${liveLayers}/${totalLayers} layers` : 'NO DATA'}</Chip>
          <Chip color={mode === 'on_demand' ? '#00f2ff' : '#64748b'}>{mode === 'on_demand' ? 'ON-DEMAND' : mode.toUpperCase()}</Chip>
          <button
            onClick={doRefresh}
            disabled={refreshing}
            style={{
              background: refreshing ? 'rgba(0,242,255,0.03)' : 'rgba(0,242,255,0.06)',
              border: '1px solid rgba(0,242,255,0.2)',
              color: refreshing ? 'rgba(0,242,255,0.4)' : '#00f2ff',
              borderRadius: 6, padding: '3px 10px', cursor: refreshing ? 'default' : 'pointer',
              fontSize: 10, fontWeight: 700, letterSpacing: 1, transition: 'all 0.2s',
            }}
            onMouseOver={(e) => { if (!refreshing) e.currentTarget.style.background = 'rgba(0,242,255,0.16)'; }}
            onMouseOut={(e) => { if (!refreshing) e.currentTarget.style.background = 'rgba(0,242,255,0.06)'; }}
          >{refreshing ? '⟳ FETCHING…' : '⟳ REFRESH'}</button>
        </div>
      }
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 28, fontWeight: 800, color: statusColor, fontFamily: MONO }}>{hasData ? liveLayers : '—'}</div>
          <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.4)', letterSpacing: 1, textTransform: 'uppercase', marginTop: 2 }}>Live Layers</div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 28, fontWeight: 800, color: isStale ? '#ffd93d' : '#00f2ff', fontFamily: MONO }}>{ageLabel}</div>
          <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.4)', letterSpacing: 1, textTransform: 'uppercase', marginTop: 2 }}>Last Fetch</div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 28, fontWeight: 800, color: '#a78bfa', fontFamily: MONO }}>{totalLayers}</div>
          <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.4)', letterSpacing: 1, textTransform: 'uppercase', marginTop: 2 }}>Total Layers</div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 16, fontWeight: 800, color: '#00f2ff', fontFamily: MONO, lineHeight: '28px' }}>⚡</div>
          <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.4)', letterSpacing: 1, textTransform: 'uppercase', marginTop: 2 }}>Zero Idle Cost</div>
        </div>
      </div>
      <div style={{ borderTop: '1px solid rgba(255,255,255,0.05)', marginTop: 14, paddingTop: 10, display: 'flex', gap: 20 }}>
        <Kv k="Mode" v={mode === 'on_demand' ? 'On-demand (power-saving)' : mode} vColor="#00f2ff" />
        <Kv k="Layers" v={['flights', 'vessels', 'fires', 'earthquakes', 'satellites'].map((l) => {
          const data = status?.[l];
          const live = data && typeof data === 'object' && data.available !== false;
          return `${l}:${live ? '✓' : '✗'}`;
        }).join('  ')} />
        {lastRefreshTs && <Kv k="Manual refresh" v={new Date(lastRefreshTs).toLocaleTimeString()} />}
      </div>
    </Panel>
  );
}
