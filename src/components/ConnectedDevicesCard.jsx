/**
 * ConnectedDevicesCard.jsx — every connected phone, with its own stats.
 *
 * Data path: the server's `system_health` frame carries `mobile.devices[]`,
 * one row per `client_id` (see MobileGatewayAgent.devices()). This renders one
 * tile per phone so two devices don't collapse into "whichever reported last".
 *
 * Falls back to the legacy single `mobile.device` sample when an older server
 * is running, so the panel degrades instead of disappearing.
 */

import React from 'react';
import useSystemHealth from '../hooks/useSystemHealth';

const MONO = "'JetBrains Mono', monospace";

// ── Formatting ────────────────────────────────────────────────────────────────
function fmtAgo(ts) {
  if (!ts) return '—';
  const secs = Math.max(0, Date.now() / 1000 - ts);
  if (secs < 5) return 'just now';
  if (secs < 60) return `${Math.round(secs)}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function fmtDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return '—';
  const s = Math.floor(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function levelColor(pct) {
  if (pct == null) return '#64748b';
  if (pct >= 85) return '#ef4444';
  if (pct >= 65) return '#ffd93d';
  return '#34d399';
}

function batteryColor(pct, charging) {
  if (pct == null) return '#64748b';
  if (charging) return '#34d399';
  if (pct <= 15) return '#ef4444';
  if (pct <= 35) return '#ffd93d';
  return '#34d399';
}

// ── Small pieces ──────────────────────────────────────────────────────────────
function Meter({ label, value, max = 100, display, color }) {
  const pct = value == null ? 0 : Math.min(100, Math.max(0, (value / max) * 100));
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, marginBottom: 3 }}>
        <span style={{ color: 'rgba(255,255,255,0.42)', letterSpacing: 0.8, textTransform: 'uppercase' }}>{label}</span>
        <span style={{ color: color || '#94a3b8', fontFamily: MONO, fontWeight: 700 }}>{display ?? (value == null ? '—' : `${value}%`)}</span>
      </div>
      <div style={{ height: 4, borderRadius: 3, background: 'rgba(255,255,255,0.07)', overflow: 'hidden' }}>
        <div style={{
          width: `${pct}%`, height: '100%', borderRadius: 3,
          background: color || '#00f2ff',
          boxShadow: pct > 0 ? `0 0 8px ${color || '#00f2ff'}60` : 'none',
          transition: 'width 0.5s ease',
        }} />
      </div>
    </div>
  );
}

function PendingTile({ device }) {
  return (
    <div style={{
      borderRadius: 12, padding: 16,
      border: '1px dashed rgba(255,255,255,0.1)',
      background: 'rgba(255,255,255,0.015)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{
          width: 7, height: 7, borderRadius: '50%', background: '#a78bfa',
          boxShadow: '0 0 10px #a78bfa', animation: 'statusPulse 1.6s infinite',
        }} />
        <span style={{ fontSize: 13, fontWeight: 700, color: '#e2e8f0' }}>{device.label || 'Phone'}</span>
      </div>
      <div style={{ marginTop: 8, fontSize: 11, color: 'rgba(255,255,255,0.35)', lineHeight: 1.5 }}>
        Connected, waiting for its first telemetry frame. An older app build may
        never send one — update the app to see battery / CPU / RAM here.
      </div>
      <div style={{ marginTop: 8, fontSize: 10, color: 'rgba(255,255,255,0.25)', fontFamily: MONO }}>
        id {String(device.id || '—').slice(0, 12)} · {device.channels} channel{device.channels === 1 ? '' : 's'}
      </div>
    </div>
  );
}

function DeviceTile({ device }) {
  const m = device.metrics || {};
  const online = !!device.connected;
  const hasMetrics = Object.keys(m).length > 0;
  if (!hasMetrics) return <PendingTile device={device} />;

  const model = [m.manufacturer, m.model].filter(Boolean).join(' ');
  const os = m.os_version || m.platform || null;
  const battery = typeof m.battery === 'number' ? m.battery : null;
  const cpu = typeof m.cpu_percent === 'number' ? m.cpu_percent : null;
  const ram = typeof m.ram_percent === 'number' ? m.ram_percent : null;
  const accent = online ? '#a78bfa' : '#64748b';

  return (
    <div style={{
      borderRadius: 12, padding: 16,
      border: `1px solid ${accent}33`,
      background: online
        ? 'linear-gradient(180deg, rgba(167,139,250,0.08), rgba(30,41,59,0.25))'
        : 'rgba(30,41,59,0.2)',
      opacity: online ? 1 : 0.72,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, marginBottom: 12 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            <span style={{
              width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
              background: online ? '#34d399' : '#64748b',
              boxShadow: online ? '0 0 10px #34d399' : 'none',
              animation: online ? 'statusPulse 1.8s infinite' : 'none',
            }} />
            <span style={{
              fontSize: 14, fontWeight: 800, color: '#e2e8f0',
              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            }}>
              {model || 'Phone'}
            </span>
          </div>
          <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', marginTop: 3, fontFamily: MONO }}>
            {os || 'unknown OS'}
            {m.android_sdk ? ` · SDK ${m.android_sdk}` : ''}
          </div>
        </div>
        <span style={{
          padding: '2px 8px', borderRadius: 999, fontSize: 9, fontWeight: 800, letterSpacing: 1,
          color: online ? '#34d399' : '#94a3b8',
          border: `1px solid ${online ? '#34d39966' : '#94a3b866'}`,
          background: online ? '#34d39914' : 'rgba(148,163,184,0.08)',
          flexShrink: 0,
        }}>
          {online ? 'LIVE' : 'LAST SEEN'}
        </span>
      </div>

      {/* Stats */}
      <Meter
        label="Battery"
        value={battery}
        display={battery == null ? '—' : `${battery}%${m.charging ? ' ⚡' : ''}`}
        color={batteryColor(battery, m.charging)}
      />
      <Meter
        label="CPU"
        value={cpu}
        display={cpu == null ? 'not reported' : `${cpu}%`}
        color={cpu == null ? '#64748b' : levelColor(cpu)}
      />
      <Meter
        label="Memory"
        value={ram}
        display={ram == null
          ? '—'
          : `${ram}%${m.ram_used_gb != null && m.ram_total_gb != null ? ` · ${m.ram_used_gb}/${m.ram_total_gb} GB` : ''}`}
        color={ram == null ? '#64748b' : levelColor(ram)}
      />

      {/* Footer */}
      <div style={{
        marginTop: 10, paddingTop: 9, borderTop: '1px solid rgba(255,255,255,0.06)',
        display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '3px 10px',
        fontSize: 10, color: 'rgba(255,255,255,0.38)',
      }}>
        <span>Channels</span>
        <span style={{ textAlign: 'right', fontFamily: MONO, color: 'rgba(255,255,255,0.62)' }}>{device.channels}</span>
        <span>Session</span>
        <span style={{ textAlign: 'right', fontFamily: MONO, color: 'rgba(255,255,255,0.62)' }}>
          {fmtDuration((device.last_seen || 0) - (device.first_seen || 0))}
        </span>
        <span>Last frame</span>
        <span style={{ textAlign: 'right', fontFamily: MONO, color: 'rgba(255,255,255,0.62)' }}>
          {online ? fmtAgo(device.metrics_ts) : fmtAgo(device.last_seen)}
        </span>
      </div>
    </div>
  );
}

// ── Panel ─────────────────────────────────────────────────────────────────────
export default function ConnectedDevicesCard() {
  const { snapshot, stale } = useSystemHealth();
  const mobile = snapshot?.mobile || {};

  const raw = Array.isArray(mobile.devices) ? mobile.devices : [];
  // Back-compat: an older backend only exposes the most recent sample.
  const devices = raw.length > 0
    ? raw
    : (mobile.device && Object.keys(mobile.device).length > 0 && mobile.connected
      ? [{
          id: 'legacy',
          label: [mobile.device.manufacturer, mobile.device.model].filter(Boolean).join(' '),
          connected: true,
          channels: mobile.connected_channels ?? 1,
          first_seen: null,
          last_seen: mobile.device_last_ts,
          metrics_ts: mobile.device_last_ts,
          metrics: mobile.device,
        }]
      : []);

  const online = devices.filter(d => d.connected);
  const reported = online.filter(d => d.metrics && Object.keys(d.metrics).length > 0);
  const reportedChannels = online.reduce((n, d) => n + (d.channels || 0), 0);
  const offline = devices.length - online.length;
  const waiting = !snapshot;

  return (
    <div style={{
      background: 'rgba(30,41,59,0.3)',
      border: `1px solid ${online.length ? 'rgba(167,139,250,0.28)' : 'rgba(255,255,255,0.07)'}`,
      borderRadius: 14, padding: 20,
      backdropFilter: 'blur(4px)',
      boxShadow: '0 4px 24px rgba(0,0,0,0.3)',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 18 }}>📱</span>
          <div>
            <div style={{ fontSize: 12, fontWeight: 800, letterSpacing: 1.4, textTransform: 'uppercase', color: '#e2e8f0' }}>
              Connected Devices
            </div>
            <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.32)', marginTop: 2 }}>
              Phones linked to this brain · live battery, CPU and memory
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          {online.length > 0 && (
            <span style={{
              padding: '3px 9px', borderRadius: 999, fontSize: 10, fontWeight: 800, letterSpacing: 1,
              color: '#34d399', border: '1px solid #34d39955', background: '#34d39914',
            }}>
              ● {online.length} ONLINE
            </span>
          )}
          {offline > 0 && (
            <span style={{
              padding: '3px 9px', borderRadius: 999, fontSize: 10, fontWeight: 800, letterSpacing: 1,
              color: '#94a3b8', border: '1px solid #94a3b855', background: 'rgba(148,163,184,0.08)',
            }}>
              {offline} RECENT
            </span>
          )}
          {stale && snapshot && (
            <span style={{
              padding: '3px 9px', borderRadius: 999, fontSize: 10, fontWeight: 800, letterSpacing: 1,
              color: '#ffd93d', border: '1px solid #ffd93d55', background: '#ffd93d14',
            }}>
              STALE
            </span>
          )}
        </div>
      </div>

      {/* Body */}
      {waiting ? (
        <div style={{ padding: '22px 0', textAlign: 'center', fontSize: 12, color: 'rgba(255,255,255,0.3)' }}>
          Waiting for the first system health frame…
        </div>
      ) : devices.length === 0 ? (
        <div style={{
          padding: '26px 16px', textAlign: 'center', fontSize: 12,
          color: 'rgba(255,255,255,0.35)', lineHeight: 1.6,
          border: '1px dashed rgba(255,255,255,0.1)', borderRadius: 10,
        }}>
          No phone connected. Open the Aariya app on a device on the same network —
          it appears here automatically with its own performance stats.
        </div>
      ) : (
        <>
          <div style={{
            display: 'grid',
            gridTemplateColumns: `repeat(auto-fit, minmax(255px, 1fr))`,
            gap: 12,
          }}>
            {devices.map((d) => <DeviceTile key={d.id || d.label} device={d} />)}
          </div>
          <div style={{
            marginTop: 12, display: 'flex', flexWrap: 'wrap', gap: 14,
            fontSize: 10, color: 'rgba(255,255,255,0.3)', fontFamily: MONO,
          }}>
            <span>{online.length} device{online.length === 1 ? '' : 's'} · {reportedChannels} channel{reportedChannels === 1 ? '' : 's'}</span>
            <span>{reported.length}/{online.length || 0} reporting telemetry</span>
            {mobile.avg_latency_ms != null && <span>{mobile.avg_latency_ms} ms avg link latency</span>}
            {mobile.peak_clients != null && <span>peak {mobile.peak_clients}</span>}
          </div>
        </>
      )}
    </div>
  );
}
