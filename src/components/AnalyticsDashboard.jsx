/**
 * AnalyticsDashboard.jsx — Aariya AI Control Center
 * ─────────────────────────────────────────────────
 * Bi-directional Neural Dashboard with:
 *   • Live personality mode switching (pushes STORE_OVERRIDE via BroadcastChannel)
 *   • Real-time signals hub (5-level severity, causal timeline)
 *   • Neural monitor (personality axes, emotion state, trust meter)
 *   • Agent Registry (auto-discovered swarm agents via /api/agents/ws)
 *   • Live event log ([SENSORS] [SWARM] [BRAIN] [LLM] [VOICE])
 *   • Auto-Adapt toggle, Memory Wipe, Session Reset
 *   • Activated via ?route=analytics OR ElectronAPI
 */

import React, { useEffect, useRef, useState } from 'react';
import useStore from '../store';
import { eventBus } from '../core/EventBus';
import { BRAIN_RAG_EVENT } from '../systems/brainClient';
import { subscribeMetrics, sendMetricsCommand } from '../systems/metricsClient';
import { isBuildSummaryFresh, BUILD_WARN_MAX_AGE_HOURS } from '../utils/buildFreshness.js';
import CveScannerPanel from './security/CveScannerPanel';
import { useSignalsStore } from '../admin/store/useSignalsStore';
import { useAdminUIStore } from '../admin/store/useAdminUIStore';
import AgentDiscoveryPanel from './AgentDiscoveryPanel';
import AgentVisualizer from './AgentVisualizer';
import RAGDashboard from './rag/RAGDashboard';
import './AnalyticsDashboard.css';

// ── Constants ────────────────────────────────────────────────────────────────

const PERSONALITY_MODES = [
  { id: 'balanced',     emoji: '⚖️',  label: 'Balanced',     desc: 'Adaptive default',       color: '#00f2ff' },
  { id: 'warm',         emoji: '☀️',  label: 'Warm',         desc: 'Friendly & Open',        color: '#ffd93d' },
  { id: 'playful',      emoji: '🎉',  label: 'Playful',      desc: 'Energetic & Teasing',    color: '#ff8fa3' },
  { id: 'intellectual', emoji: '🧠',  label: 'Intellectual', desc: 'Analytical & Curious',   color: '#6bcbef' },
  { id: 'empathetic',   emoji: '💙',  label: 'Empathetic',   desc: 'Deep emotional support', color: '#a78bfa' },
  { id: 'assertive',    emoji: '⚡',  label: 'Assertive',    desc: 'Direct & Confident',     color: '#fb923c' },
  { id: 'cold',         emoji: '🧊',  label: 'Cold',         desc: 'Reserved & Minimal',     color: '#64748b' },
  { id: 'creative',     emoji: '🎨',  label: 'Creative',     desc: 'Imaginative & Free',     color: '#34d399' },
];

const TABS = [
  { id: 'overview',      label: 'Overview',       icon: '📊' },
  { id: 'control',       label: 'Control',        icon: '🎛️' },
  { id: 'signals',       label: 'Signals',        icon: '🐞' },
  { id: 'agents',        label: 'Agent Registry', icon: '🤖' },
  { id: 'log',           label: 'Event Log',      icon: '📋' },
  { id: 'personality3d', label: 'Personality 3D', icon: '🔮' },
  { id: 'security',      label: 'Security',       icon: '🔐' },
  { id: 'build',         label: 'Build',          icon: '📦' },
  { id: 'rag',           label: 'RAG Pipeline',   icon: <span style={{ fontSize: '0.85em' }}>🧠</span> },
];

const SEV_COLOR = {
  critical: '#ef4444',
  high:     '#f97316',
  medium:   '#3b82f6',
  low:      '#10b981',
  info:     '#06b6d4',
};

const LOG_TAG_COLOR = {
  SENSORS: '#00bcd4',
  SWARM:   '#ffd93d',
  BRAIN:   '#ff8fa3',
  LLM:     '#a78bfa',
  VOICE:   '#34d399',
  SYSTEM:  '#94a3b8',
};

// ── BroadcastChannel bridge ──────────────────────────────────────────────────
const BC = (() => {
  try { return new BroadcastChannel('aariya_control'); }
  catch { return null; }
})();

function publishOverride(type, payload) {
  BC?.postMessage({ type, ...payload });
}

// ── Hook: live event log + connectivity from the shared /ws/brain_metrics ────
// ONE shared socket serves the event log, online status, latency ping and
// signals hub (previously three separate connections to the same endpoint all
// received duplicate broadcasts).
function useLiveEventLog({ onSignal } = {}) {
  const [log, setLog] = useState([]);
  const [isOnline, setIsOnline] = useState(false);
  const [pingMs, setPingMs] = useState(null);
  const onSignalRef = useRef(onSignal);
  onSignalRef.current = onSignal;

  useEffect(() => {
    const unsub = subscribeMetrics(
      () => true,
      (msg) => {
        if (msg.type === 'pong') setPingMs(0);
        if (msg.type === 'override_mode') {
          useStore.getState().setPersonalityPreset?.(msg.mode);
        }
        if (msg.type === 'signal' && msg.signal) {
          const s = msg.signal;
          if (onSignalRef.current) onSignalRef.current(s);
          const tag = s.source?.system?.toUpperCase() || 'SYSTEM';
          setLog(prev => [{
            id: s.id || String(Date.now()),
            ts: s.timestamp || null,
            tag,
            text: s.payload?.title || s.type || 'Event',
            severity: s.severity || 'info',
          }, ...prev].slice(0, 200));
        }
        if (msg.type === 'log_event') {
          setLog(prev => [{
            id: msg.id || String(Date.now()),
            ts: msg.timestamp || null,
            tag: msg.tag || 'SYSTEM',
            text: msg.message || '',
            severity: msg.severity || 'info',
          }, ...prev].slice(0, 200));
        }
      }
    );

    const unsubOnline = subscribeMetrics(
      (m) => m.type === '__conn',
      (m) => setIsOnline(!!m.connected)
    );

    return () => { unsub(); unsubOnline(); };
  }, []);

  return [log, () => setLog([]), isOnline, pingMs];
}

// ── Hook: synthetic demo log generator (when offline) ────────────────────────
function useSyntheticLog(isOnline) {
  const [demoLog, setDemoLog] = useState([]);

  useEffect(() => {
    if (isOnline) return;
    const DEMO = [
      { tag: 'SENSORS', text: 'Audio energy spike detected — VAD triggered', severity: 'info' },
      { tag: 'SWARM',   text: 'EmotionAgent summoned — fusing multimodal inputs', severity: 'info' },
      { tag: 'BRAIN',   text: 'State transition: NEUTRAL → WARM (trust=0.71)', severity: 'low' },
      { tag: 'LLM',     text: 'Token stream started — 42 tokens generated', severity: 'info' },
      { tag: 'VOICE',   text: 'TTS synthesis complete — 1.2s playback', severity: 'info' },
      { tag: 'SWARM',   text: 'RiskAgent: no boundary violations', severity: 'low' },
      { tag: 'BRAIN',   text: 'Memory L2 write — significance score: 0.74', severity: 'low' },
      { tag: 'SENSORS', text: 'Face detected — valence: +0.62, arousal: 0.48', severity: 'info' },
    ];
    let i = 0;
    const timer = setInterval(() => {
      const item = DEMO[i % DEMO.length];
      setDemoLog(prev => [{
        id: Date.now() + Math.random(),
        ts: Date.now() / 1000,
        tag: item.tag,
        text: item.text,
        severity: item.severity,
      }, ...prev].slice(0, 200));
      i++;
    }, 1800);
    return () => clearInterval(timer);
  }, [isOnline]);

  return demoLog;
}

// ── Hook: live security stream from /ws/brain (reads state_update.security) ──
function useSecurityStream() {
  const [secData, setSecData] = React.useState(null);
  const wsRef = React.useRef(null);
  const retryRef = React.useRef(null);
  const unmountedRef = React.useRef(false);

  React.useEffect(() => {
    unmountedRef.current = false;

    function connect() {
      if (unmountedRef.current) return;
      const host = window.location.hostname || 'localhost';
      // Connect to the dedicated 2-second background polling endpoint
      const ws = new WebSocket(`ws://${host}:8000/api/security/stream`);
      wsRef.current = ws;

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          // Cognitive output: state_update.security
          const sec = msg?.state_update?.security;
          if (sec && (sec.issues || sec.risk)) setSecData(sec);
        } catch { /* ignore */ }
      };

      ws.onclose = () => {
        if (!unmountedRef.current)
          retryRef.current = setTimeout(connect, 5000);
      };
      ws.onerror = () => ws.close();
    }

    connect();
    return () => {
      unmountedRef.current = true;
      clearTimeout(retryRef.current);
      wsRef.current?.close();
    };
  }, []);

  return secData;
}

// ── Hook: poll /api/emotion/predictor for LSTM training status + forecast ────
// Also listens on ws/brain_metrics for the daemon's `autonomy.model_trained`
// event and refetches immediately, so the card flips to TRAINED the moment a
// retrain completes instead of waiting for the next poll.
function usePredictorStatus(pollMs = 15000) {
  const [payload, setPayload] = useState(null);
  const [online, setOnline] = useState(false);
  const inFlightRef = useRef(false);
  const pendingRefreshRef = useRef(false); // event arrived while polling

  useEffect(() => {
    let mounted = true;
    const host = window.location.hostname || 'localhost';
    const url = `http://${host}:8000/api/emotion/predictor`;
    const fallbackUrl = `http://${host}:8000/api/autonomy/state`;

    async function fetchPrimary() {
      try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (mounted) {
          setPayload({ ...data, source: 'api' });
          setOnline(true);
        }
        return true;
      } catch {
        return false;
      }
    }

    // Fallback: the daemon's inner-world payload carries the same predictor
    // telemetry (status / checkpoint age / corpus / forecast), so the card
    // keeps working even when /api/emotion/predictor is unreachable. Field
    // names already match — only meta needs to be re-nested and the source
    // tagged so the card can show it's reading inner-world telemetry.
    function normalizeInnerWorld(inner) {
      const p = inner?.predictor || {};
      return {
        status: p.status || 'untrained',
        predictor: p.predictor || null,
        meta: {
          trained_at: p.trained_at ?? null,
          count: p.count ?? 0,
          seed_count: p.seed_count ?? 0,
        },
        corpus: p.corpus || { snapshots: 0, sessions: 0 },
        forecast: p.forecast || null,
        source: 'inner-world',
      };
    }

    async function fetchFallback() {
      try {
        const res = await fetch(fallbackUrl);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const inner = await res.json();
        if (mounted) {
          setPayload(normalizeInnerWorld(inner));
          setOnline(false); // full endpoint unreachable — card stays honest
        }
        return true;
      } catch {
        return false;
      }
    }

    async function poll() {
      if (inFlightRef.current) return; // never stack overlapping requests
      inFlightRef.current = true;
      try {
        // Primary first; the inner-world payload is the fallback data source
        // when the dedicated endpoint is down. Each helper handles its own
        // failures, so no error escapes here.
        if (!(await fetchPrimary())) {
          await fetchFallback();
        }
      } finally {
        inFlightRef.current = false;
        // An event-driven refresh was queued while we were busy — run it now
        // so the card never misses the training-complete update.
        if (pendingRefreshRef.current && mounted) {
          pendingRefreshRef.current = false;
          poll();
        }
      }
    }

    // Event-driven refresh: the daemon broadcasts autonomy.model_trained
    // (with fresh telemetry) to every connected surface after a retrain.
    // Reuses the shared /ws/brain_metrics connection — no separate socket.
    const unsubModelTrained = subscribeMetrics(
      (m) => m.type === 'autonomy.model_trained',
      () => {
        if (inFlightRef.current) {
          pendingRefreshRef.current = true; // retry right after the in-flight poll
        } else {
          poll();
        }
      }
    );

    poll();
    const timer = setInterval(poll, pollMs);
    return () => {
      mounted = false;
      clearInterval(timer);
      unsubModelTrained();
    };
  }, [pollMs]);

  return { payload, online };
}

// ── Main Component ────────────────────────────────────────────────────────────
export default function AnalyticsDashboard({ isPopup = false }) {
  // Store hooks
  const {
    trust, personality, emotions, userEmotion, userAudioStats,
    personalityPreset,
    signals: legacySignals, addSignal: addLegacySignal,
    setPersonalityPreset, clearSignals,
    thinking, speaking, listening, faceDetected,
  } = useStore();

  const { addSignal, signals: adminSignals, acknowledge, resolve } = useSignalsStore();
  useAdminUIStore();

  // Local state
  const [tab, setTab] = useState('overview');
  const [sigFilter, setSigFilter] = useState('all');
  const [selectedSignal, setSelectedSignal] = useState(null);
  const [selectedRegistryAgent, setSelectedRegistryAgent] = useState(null);
  const [autoAdapt, setAutoAdapt] = useState(true);
  const [uptime, setUptime] = useState(0);
  const [memoryWiped, setMemoryWiped] = useState(false);
  // Authority-layer feedback: the last authority.ack frame from the server
  // (executed on /ws/brain_metrics), so the UI confirms server-side success.
  const [authStatus, setAuthStatus] = useState(null);
  const mountTimeRef = useRef(0);

  // Security stream
  const securityData = useSecurityStream();

  // Meeting Mode state
  const [meetingMode, setMeetingMode] = useState({
    active: false, speaker_count: 1, direct_address_window: 30,
    base_window: 30, ai_names: ['aariya', 'aaria', 'arya'],
  });


  const toggleMeeting = async () => {
    try {
      const res = await fetch(
        `http://${window.location.hostname || 'localhost'}:8000/api/meeting/toggle`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ active: null }) }
      );
      if (res.ok) { const d = await res.json(); setMeetingMode(d.status); }
    } catch { setMeetingMode(m => ({ ...m, active: !m.active })); }
  };

  const setMeetingWindow = async (secs) => {
    try {
      await fetch(
        `http://${window.location.hostname || 'localhost'}:8000/api/meeting/window`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ seconds: secs }) }
      );
      setMeetingMode(m => ({ ...m, base_window: secs, direct_address_window: secs }));
    } catch { /* ignore */ }
  };

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const res = await fetch(`http://${window.location.hostname || 'localhost'}:8000/api/meeting/status`);
        if (res.ok && mounted) setMeetingMode(await res.json());
      } catch { /* offline */ }
    })();
    return () => { mounted = false; };
  }, []);

  // Event log + connectivity from a single /ws/brain_metrics socket
  const [liveLog, clearLog, isOnline, pingMs] = useLiveEventLog({
    onSignal: (s) => { addSignal(s); addLegacySignal(s); },
  });
  const demoLog = useSyntheticLog(isOnline);
  const eventLog = isOnline ? liveLog : demoLog;

  // Stats derived from signals
  const allSignals = adminSignals.length > 0 ? adminSignals : legacySignals;
  const critCount  = allSignals.filter(s => s.severity === 'critical').length;
  const unreadCount = allSignals.filter(s => s.status === 'new').length;

  // ── RAG telemetry ───────────────────────────────────────────────────────────
  // RAG traces ride on the single brain socket (ai_response.meta.rag) via the
  // shared event bus — no second /ws/dashboard/stream connection needed.
  const [ragData, setRagData] = useState(null);
  useEffect(() => {
    const unsub = eventBus.subscribe(BRAIN_RAG_EVENT, setRagData);
    return () => unsub();
  }, []);

  // ── BroadcastChannel listener (receive overrides from main window) ─────────
  useEffect(() => {
    if (!BC) return;
    const handler = (e) => {
      if (e.data?.type === 'STORE_OVERRIDE') {
        if (e.data.mode) setPersonalityPreset(e.data.mode);
        if (typeof e.data.autoAdapt === 'boolean') setAutoAdapt(e.data.autoAdapt);
      }
    };
    BC.addEventListener('message', handler);
    return () => BC.removeEventListener('message', handler);
  }, [setPersonalityPreset]);

  // ── Authority-layer ack listener ─────────────────────────────────────────
  // The server replies to every command on the shared /ws/brain_metrics socket
  // with an authority.ack frame; surface it in the Control tab so the laptop
  // operator sees the wipe / persona change actually executed server-side.
  useEffect(() => {
    const unsub = subscribeMetrics(
      (m) => m.type === 'authority.ack',
      (m) => setAuthStatus({ ...m, at: Date.now() })
    );
    return unsub;
  }, []);

  // uptime — mountTimeRef is set on first paint via useEffect to avoid Date.now() at render time
  useEffect(() => {
    mountTimeRef.current = Date.now();
    const t = setInterval(() => setUptime(Math.floor((Date.now() - mountTimeRef.current) / 1000)), 1000);
    return () => clearInterval(t);
  }, []);

  // ── Handlers ──────────────────────────────────────────────────────────────
  const handleModeChange = (mode) => {
    setPersonalityPreset(mode);
    publishOverride('STORE_OVERRIDE', { mode });
    // AUTHORITY LAYER: also rewrite the persona server-side so every surface
    // (phones, Unity, other dashboards) inherits the mode, not just this tab.
    sendMetricsCommand('set_personality', { preset: mode });
  };

  const handleAutoAdapt = () => {
    const next = !autoAdapt;
    setAutoAdapt(next);
    publishOverride('STORE_OVERRIDE', { autoAdapt: next });
  };

  const handleMemoryWipe = () => {
    if (!window.confirm('Wipe Aariya\u2019s working memory on the server? This is executed by the authority layer and cannot be undone.')) return;
    setMemoryWiped(true);
    clearSignals();
    publishOverride('ACTION', { action: 'memory_wipe' });
    sendMetricsCommand('wipe_memory');
    setTimeout(() => setMemoryWiped(false), 3000);
  };

  const handleForceMode = (mode) => {
    sendMetricsCommand('force_mode', { mode });
  };

  const handleSessionReset = () => {
    publishOverride('ACTION', { action: 'session_reset' });
  };

  // ── Route guard ───────────────────────────────────────────────────────────
  const urlParams = new URLSearchParams(window.location.search);
  const isAnalyticsRoute = isPopup || urlParams.get('route') === 'analytics' || window.location.hash.includes('analytics');
  if (!isAnalyticsRoute) return null;

  // ── Filtered signals ──────────────────────────────────────────────────────
  const filteredSigs = allSignals.filter(s => {
    if (sigFilter === 'all') return true;
    if (sigFilter === 'critical') return s.severity === 'critical' || s.severity === 'high';
    if (sigFilter === 'info') return s.severity === 'info' || s.severity === 'low';
    return s.type === sigFilter;
  });

  const fmtUptime = (s) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}m ${sec}s`;
  };

  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 100000, background: '#050508', display: 'flex', flexDirection: 'column', fontFamily: "'Inter', 'system-ui', sans-serif" }}>

      {/* ── TOP HEADER ── */}
      <header style={{
        display: 'flex', alignItems: 'center', padding: '0 24px',
        height: 56, background: '#0a0a10',
        borderBottom: '1px solid rgba(0,242,255,0.12)',
        flexShrink: 0, gap: 16,
      }}>
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginRight: 8 }}>
          <div style={{
            width: 32, height: 32, borderRadius: '50%',
            background: 'radial-gradient(circle, #ff8fa3, #c0392b)',
            boxShadow: '0 0 14px rgba(255,143,163,0.5)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 14,
          }}>🧠</div>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: 2, color: '#ff8fa3', textTransform: 'uppercase' }}>Aariya</div>
            <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', letterSpacing: 1.5, textTransform: 'uppercase' }}>AI Control Center</div>
          </div>
        </div>

        {/* Status chips */}
        <StatusChip label="BRAIN" active={isOnline} color="#00f2ff" />
        <StatusChip label="THINKING" active={thinking} color="#ffd93d" pulse />
        <StatusChip label="SPEAKING" active={speaking} color="#ff8fa3" pulse />
        <StatusChip label="LISTENING" active={listening} color="#34d399" pulse />
        <StatusChip label="FACE" active={faceDetected} color="#a78bfa" />

        <div style={{ flex: 1 }} />

        {/* Right stats */}
        <HeaderStat label="UPTIME" value={fmtUptime(uptime)} />
        <HeaderStat label="PING" value={pingMs ? `${pingMs}ms` : '—'} color={pingMs > 200 ? '#ef4444' : '#10b981'} />
        <HeaderStat label="TRUST" value={`${Math.round((trust || 0.5) * 100)}%`} color={trust > 0.6 ? '#10b981' : trust > 0.35 ? '#ffd93d' : '#ef4444'} />
        <HeaderStat label="MODE" value={(personalityPreset || 'balanced').toUpperCase()} color="#ff8fa3" />

        {critCount > 0 && (
          <div style={{
            background: 'rgba(239,68,68,0.15)', border: '1px solid #ef4444',
            borderRadius: 20, padding: '3px 12px', fontSize: 11, color: '#ef4444',
            fontWeight: 700, animation: 'criticalPulse 2s infinite',
          }}>
            ⚠ {critCount} CRITICAL
          </div>
        )}

        <button
          onClick={() => window.close()}
          style={{
            background: 'rgba(255,68,68,0.1)', border: '1px solid rgba(255,68,68,0.3)',
            color: '#ff6666', borderRadius: 6, padding: '6px 14px',
            cursor: 'pointer', fontSize: 12, fontWeight: 600,
            transition: 'all 0.2s',
          }}
          onMouseOver={e => e.currentTarget.style.background = 'rgba(255,68,68,0.25)'}
          onMouseOut={e => e.currentTarget.style.background = 'rgba(255,68,68,0.1)'}
        >✕ Close</button>
      </header>

      {/* ── TAB BAR ── */}
      <div style={{
        display: 'flex', gap: 2, padding: '8px 24px 0',
        background: 'rgba(0,0,0,0.4)', borderBottom: '1px solid rgba(255,255,255,0.05)',
        flexShrink: 0,
      }}>
        {TABS.map(t => (
          <TabButton
            key={t.id}
            active={tab === t.id}
            onClick={() => setTab(t.id)}
            badge={t.id === 'signals' && unreadCount > 0 ? unreadCount : null}
          >
            <span style={{ marginRight: 6 }}>{t.icon}</span>
            {t.label}
          </TabButton>
        ))}
      </div>

      {/* ── MAIN CONTENT ── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* ── SIDEBAR ── */}
        <aside style={{
          width: 240, background: '#0a0a0f',
          borderRight: '1px solid rgba(255,255,255,0.05)',
          display: 'flex', flexDirection: 'column', overflow: 'hidden', flexShrink: 0,
          padding: '16px 0',
        }}>
          <NeuralMonitorPanel
            trust={trust}
            personality={personality}
            emotions={emotions}
            userEmotion={userEmotion}
            userAudioStats={userAudioStats}
            thinking={thinking}
            personalityPreset={personalityPreset}
          />
        </aside>

        {/* ── PAGE CONTENT ── */}
        <main style={{ flex: 1, overflowY: 'auto', padding: 28, background: 'radial-gradient(ellipse at top right, rgba(255,143,163,0.03) 0%, transparent 60%)' }}>

          {tab === 'overview' && (
            <OverviewTab
              allSignals={allSignals}
              trust={trust}
              personality={personality}
              emotions={emotions}
              personalityPreset={personalityPreset}
              isOnline={isOnline}
              thinking={thinking}
              speaking={speaking}
              listening={listening}
            />
          )}

          {tab === 'control' && (
            <ControlTab
              personalityPreset={personalityPreset}
              autoAdapt={autoAdapt}
              onModeChange={handleModeChange}
              onAutoAdapt={handleAutoAdapt}
              onMemoryWipe={handleMemoryWipe}
              onSessionReset={handleSessionReset}
              memoryWiped={memoryWiped}
              isOnline={isOnline}
              meetingMode={meetingMode}
              onToggleMeeting={toggleMeeting}
              onSetMeetingWindow={setMeetingWindow}
              authStatus={authStatus}
              onForceMode={handleForceMode}
            />
          )}

          {tab === 'signals' && (
            <SignalsTab
              signals={filteredSigs}
              filter={sigFilter}
              onFilter={setSigFilter}
              selected={selectedSignal}
              onSelect={setSelectedSignal}
              onAck={acknowledge}
              onResolve={resolve}
            />
          )}

          {tab === 'agents' && (() => {
            return (
              <div style={{ display: 'grid', gridTemplateColumns: 'minmax(320px, 440px) 1fr', gap: 20, height: '100%' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <SectionHeader title="Agent Registry" sub="Live discovery of FIXV4 swarm agents via /api/agents/ws" />
                  <AgentDiscoveryPanel onAgentClick={(agent) => setSelectedRegistryAgent(agent)} />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                  <AgentVisualizer 
                     signals={allSignals} 
                     selectedAgent={selectedRegistryAgent} 
                     onSelectAgent={setSelectedRegistryAgent} 
                  />
                </div>
              </div>
            );
          })()}


          {tab === 'log' && (
            <EventLogTab log={eventLog} onClear={clearLog} isOnline={isOnline} />
          )}

          {tab === 'personality3d' && (
            <PersonalitySpace3DTab
              trust={trust}
              userEmotion={userEmotion}
              personality={personality}
              personalityPreset={personalityPreset}
            />
          )}

          {tab === 'security' && (
            <SecurityTab data={securityData} />
          )}

          {tab === 'build' && (
            <BuildTab />
          )}

          {tab === 'rag' && (
            <RAGDashboard rag={ragData} />
          )}

        </main>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// SUB-COMPONENTS
// ═══════════════════════════════════════════════════════════════════════════════

// ── Status Chip ───────────────────────────────────────────────────────────────
function StatusChip({ label, active, color, pulse }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 5,
      padding: '3px 10px', borderRadius: 20,
      background: active ? `${color}18` : 'rgba(255,255,255,0.03)',
      border: `1px solid ${active ? `${color}55` : 'rgba(255,255,255,0.07)'}`,
      fontSize: 10, letterSpacing: 1, fontWeight: 700,
      color: active ? color : 'rgba(255,255,255,0.25)',
      transition: 'all 0.3s ease',
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: '50%',
        background: active ? color : 'rgba(255,255,255,0.15)',
        boxShadow: active && pulse ? `0 0 8px ${color}` : 'none',
        animation: active && pulse ? 'statusPulse 1.5s infinite' : 'none',
      }} />
      {label}
    </div>
  );
}

// ── Header Stat ───────────────────────────────────────────────────────────────
function HeaderStat({ label, value, color = '#fff' }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      padding: '4px 12px', borderRadius: 6,
      background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)',
      minWidth: 60,
    }}>
      <span style={{ fontSize: 9, color: 'rgba(255,255,255,0.35)', letterSpacing: 1.5, marginBottom: 2, textTransform: 'uppercase' }}>{label}</span>
      <span style={{ fontSize: 13, fontWeight: 700, color, fontFamily: "'JetBrains Mono', monospace" }}>{value}</span>
    </div>
  );
}

// ── Tab Button ────────────────────────────────────────────────────────────────
function TabButton({ active, onClick, children, badge }) {
  return (
    <button
      onClick={onClick}
      style={{
        position: 'relative',
        padding: '10px 20px',
        border: 'none', borderRadius: '8px 8px 0 0',
        color: active ? '#00f2ff' : 'rgba(255,255,255,0.35)',
        fontSize: 12, fontWeight: 700, letterSpacing: 0.8,
        cursor: 'pointer', textTransform: 'uppercase',
        background: active ? 'linear-gradient(to bottom, rgba(0,242,255,0.08), transparent)' : 'transparent',
        borderBottom: active ? '2px solid #00f2ff' : '2px solid transparent',
        transition: 'all 0.25s',
        display: 'flex', alignItems: 'center', gap: 6,
      }}
      onMouseOver={e => { if (!active) e.currentTarget.style.color = 'rgba(255,255,255,0.7)'; }}
      onMouseOut={e => { if (!active) e.currentTarget.style.color = 'rgba(255,255,255,0.35)'; }}
    >
      {children}
      {badge > 0 && (
        <span style={{
          background: '#dc2626', color: '#fff',
          fontSize: 9, fontWeight: 800,
          padding: '1px 6px', borderRadius: 10,
          minWidth: 16, textAlign: 'center',
        }}>{badge}</span>
      )}
    </button>
  );
}

// ── Section Header ────────────────────────────────────────────────────────────
function SectionHeader({ title, sub }) {
  return (
    <div style={{ marginBottom: 4 }}>
      <h2 style={{ margin: 0, fontSize: 18, fontWeight: 300, color: '#fff', letterSpacing: 0.5 }}>{title}</h2>
      {sub && <p style={{ margin: '4px 0 0', fontSize: 12, color: 'rgba(255,255,255,0.35)' }}>{sub}</p>}
    </div>
  );
}

// ── Card ──────────────────────────────────────────────────────────────────────
function Card({ children, style, accentColor }) {
  return (
    <div style={{
      background: 'rgba(30,41,59,0.3)',
      border: `1px solid ${accentColor ? `${accentColor}28` : 'rgba(255,255,255,0.07)'}`,
      borderRadius: 14, padding: 20,
      backdropFilter: 'blur(4px)',
      boxShadow: '0 4px 24px rgba(0,0,0,0.3)',
      ...style,
    }}>
      {children}
    </div>
  );
}

// ── Progress Bar ──────────────────────────────────────────────────────────────
function Bar({ label, value, color, min = 0, max = 1, showVal = true }) {
  const pct = Math.min(100, Math.max(0, ((value - min) / (max - min)) * 100));
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'rgba(255,255,255,0.5)', marginBottom: 4 }}>
        <span style={{ textTransform: 'capitalize', letterSpacing: 0.5 }}>{label}</span>
        {showVal && <span style={{ color, fontFamily: 'monospace', fontWeight: 700 }}>{typeof value === 'number' ? value.toFixed(2) : value}</span>}
      </div>
      <div style={{ height: 5, background: 'rgba(255,255,255,0.07)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{
          width: `${pct}%`, height: '100%',
          background: color,
          borderRadius: 3,
          transition: 'width 0.4s ease',
          boxShadow: pct > 0 ? `0 0 8px ${color}60` : 'none',
        }} />
      </div>
    </div>
  );
}

// ── Neural Monitor Sidebar ────────────────────────────────────────────────────
function NeuralMonitorPanel({ trust, personality, emotions, userEmotion, userAudioStats, thinking, personalityPreset }) {
  const emo = userEmotion || { valence: 0, arousal: 0 };
  const pers = personality || {};
  const emo2 = emotions || {};
  const audio = userAudioStats || { energy: 0 };

  const trustTier = trust > 0.85 ? 'INTIMATE' : trust > 0.6 ? 'WARM' : trust > 0.4 ? 'NEUTRAL' : trust > 0.2 ? 'GUARDED' : 'DEFENSIVE';
  const trustColor = trust > 0.6 ? '#10b981' : trust > 0.35 ? '#ffd93d' : '#ef4444';

  return (
    <div style={{ padding: '0 14px', display: 'flex', flexDirection: 'column', gap: 18, overflow: 'auto', flex: 1 }}>
      {/* Status badges */}
      <div>
        <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', letterSpacing: 2, marginBottom: 8, textTransform: 'uppercase' }}>Neural Monitor</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          <MiniChip active={thinking} color="#ffd93d" label={thinking ? '⚡ THINKING' : '💤 IDLE'} />
          <MiniChip active={true} color="#ff8fa3" label={(personalityPreset || 'balanced').toUpperCase()} />
        </div>
      </div>

      {/* Trust */}
      <div>
        <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', letterSpacing: 2, marginBottom: 6, textTransform: 'uppercase' }}>Trust Score</div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
          <span style={{ fontSize: 22, fontWeight: 700, color: trustColor, fontFamily: 'monospace' }}>{Math.round((trust || 0.5) * 100)}%</span>
          <span style={{ fontSize: 10, color: trustColor, fontWeight: 700, letterSpacing: 1 }}>{trustTier}</span>
        </div>
        <div style={{ height: 6, background: 'rgba(255,255,255,0.07)', borderRadius: 3, overflow: 'hidden' }}>
          <div style={{ width: `${(trust || 0.5) * 100}%`, height: '100%', background: `linear-gradient(90deg, ${trustColor}99, ${trustColor})`, borderRadius: 3, transition: 'width 0.5s ease' }} />
        </div>
      </div>

      {/* Personality axes */}
      <div>
        <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', letterSpacing: 2, marginBottom: 6, textTransform: 'uppercase' }}>Personality Axes</div>
        <Bar label="Warmth"       value={pers.warmth || 0}       color="#ffd93d" />
        <Bar label="Energy"       value={pers.energy || 0}       color="#fb923c" />
        <Bar label="Assertiveness" value={pers.assertiveness || 0} color="#f43f5e" />
        <Bar label="Formality"    value={pers.formality || 0}    color="#6bcbef" />
      </div>

      {/* Emotion state */}
      <div>
        <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', letterSpacing: 2, marginBottom: 6, textTransform: 'uppercase' }}>Emotion State (AI)</div>
        {Object.entries(emo2).sort(([, a], [, b]) => b - a).slice(0, 4).map(([k, v]) => (
          <Bar key={k} label={k} value={v} color="#ff8fa3" max={1.5} />
        ))}
      </div>

      {/* User emotion */}
      <div>
        <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', letterSpacing: 2, marginBottom: 6, textTransform: 'uppercase' }}>User V/A Space</div>
        <VADot valence={emo.valence} arousal={emo.arousal} />
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
          <StatPill label="Valence" value={(emo.valence || 0).toFixed(2)} color={emo.valence > 0 ? '#10b981' : '#ef4444'} />
          <StatPill label="Arousal" value={(emo.arousal || 0).toFixed(2)} color="#ffd93d" />
        </div>
      </div>

      {/* Audio */}
      <div>
        <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', letterSpacing: 2, marginBottom: 6, textTransform: 'uppercase' }}>Audio Input</div>
        <Bar label="Energy" value={Math.min(1, (audio.energy || 0) / 255)} color="#00bcd4" />
        {audio.isLoud && (
          <div style={{ fontSize: 10, color: '#ef4444', fontWeight: 600, marginTop: 4 }}>⚠ LOUD DETECTED</div>
        )}
      </div>
    </div>
  );
}

// ── VA Space dot ──────────────────────────────────────────────────────────────
function VADot({ valence = 0, arousal = 0 }) {
  const x = ((valence + 1) / 2) * 100;
  const y = (1 - arousal) * 100;
  return (
    <div style={{ position: 'relative', width: '100%', paddingBottom: '66%', background: 'rgba(255,255,255,0.03)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.07)', overflow: 'hidden' }}>
      <div style={{ position: 'absolute', inset: 0 }}>
        {/* Axes */}
        <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, background: 'rgba(255,255,255,0.08)' }} />
        <div style={{ position: 'absolute', top: '50%', left: 0, right: 0, height: 1, background: 'rgba(255,255,255,0.08)' }} />
        {/* Labels */}
        <span style={{ position: 'absolute', left: 4, fontSize: 8, color: 'rgba(255,255,255,0.2)', top: '50%', transform: 'translateY(-50%)' }}>NEG</span>
        <span style={{ position: 'absolute', right: 4, fontSize: 8, color: 'rgba(255,255,255,0.2)', top: '50%', transform: 'translateY(-50%)' }}>POS</span>
        <span style={{ position: 'absolute', top: 2, left: '50%', fontSize: 8, color: 'rgba(255,255,255,0.2)', transform: 'translateX(-50%)' }}>HIGH</span>
        <span style={{ position: 'absolute', bottom: 2, left: '50%', fontSize: 8, color: 'rgba(255,255,255,0.2)', transform: 'translateX(-50%)' }}>LOW</span>
        {/* Dot */}
        <div style={{
          position: 'absolute',
          left: `calc(${x}% - 5px)`,
          top: `calc(${y}% - 5px)`,
          width: 10, height: 10, borderRadius: '50%',
          background: '#ff8fa3',
          boxShadow: '0 0 10px #ff8fa3, 0 0 20px rgba(255,143,163,0.4)',
          transition: 'left 0.4s ease, top 0.4s ease',
        }} />
      </div>
    </div>
  );
}

// ── Mini chips ────────────────────────────────────────────────────────────────
function MiniChip({ active, color, label }) {
  return (
    <span style={{
      padding: '2px 8px', borderRadius: 4, fontSize: 9, fontWeight: 700, letterSpacing: 0.5,
      background: active ? `${color}22` : 'rgba(255,255,255,0.04)',
      color: active ? color : 'rgba(255,255,255,0.3)',
      border: `1px solid ${active ? `${color}44` : 'rgba(255,255,255,0.06)'}`,
    }}>{label}</span>
  );
}

function StatPill({ label, value, color }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
      <span style={{ fontSize: 11, fontWeight: 700, color, fontFamily: 'monospace' }}>{value}</span>
      <span style={{ fontSize: 8, color: 'rgba(255,255,255,0.3)', letterSpacing: 1, textTransform: 'uppercase' }}>{label}</span>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// TAB PAGES
// ═══════════════════════════════════════════════════════════════════════════════

// ── Predictor Status Card ─────────────────────────────────────────────────────
const PRED_LABEL = { fontSize: 9, color: 'rgba(255,255,255,0.3)', letterSpacing: 2, marginBottom: 6, textTransform: 'uppercase' };
const PRED_KV = { display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 };
const PRED_KV_KEY = { color: 'rgba(255,255,255,0.35)', letterSpacing: 1 };
const PRED_KV_VAL = { color: '#fff', fontFamily: 'monospace', fontWeight: 700 };

function RiskBadge({ active, color, label }) {
  return (
    <span style={{
      padding: '2px 8px', borderRadius: 4, fontSize: 9, fontWeight: 800, letterSpacing: 1,
      background: active ? `${color}22` : 'rgba(255,255,255,0.03)',
      color: active ? color : 'rgba(255,255,255,0.35)',
      border: `1px solid ${active ? `${color}55` : 'rgba(255,255,255,0.06)'}`,
      whiteSpace: 'nowrap',
    }}>{label}</span>
  );
}

function PredictorStatusCard() {
  const { payload, online } = usePredictorStatus();

  const trained = payload?.status === 'trained';
  const statusColor = !online ? '#64748b' : trained ? '#10b981' : '#ffd93d';
  const statusLabel = !online ? 'OFFLINE' : trained ? 'TRAINED' : 'UNTRAINED';
  const meta = payload?.meta || {};
  const corpus = payload?.corpus || { snapshots: 0, sessions: 0 };
  const f = payload?.forecast || null;
  const valence = f ? f.future_valence : null;
  const totalRecords = corpus.snapshots + corpus.sessions;
  const fromInnerWorld = payload?.source === 'inner-world';
  // Inner-world telemetry carries trained_at only when a checkpoint exists.
  const trainedAt = meta.trained_at;
  const lastTrained = trainedAt
    ? new Date(trainedAt * 1000).toLocaleString()
    : '—';
  const trend = f && Math.abs(f.velocity_valence) > 0.01
    ? (f.velocity_valence > 0 ? '↗' : '↘')
    : '→';

  return (
    <Card accentColor={statusColor}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 4 }}>🧠 Emotion Predictor</div>
            {fromInnerWorld && (
              <span style={{
                fontSize: 9, fontWeight: 700, letterSpacing: 1,
                padding: '2px 8px', borderRadius: 4,
                background: 'rgba(148,163,184,0.12)',
                border: '1px solid rgba(148,163,184,0.35)',
                color: '#94a3b8',
                marginBottom: 4, whiteSpace: 'nowrap',
              }}>INNER-WORLD</span>
            )}
          </div>
          <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.35)' }}>
            PyTorch LSTM · self-retrains on the autonomy daemon cadence
          </div>
        </div>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0,
          padding: '4px 12px', borderRadius: 20,
          background: `${statusColor}18`, border: `1px solid ${statusColor}55`,
          color: statusColor, fontSize: 10, fontWeight: 800, letterSpacing: 1.5,
        }}>
          <span style={{
            width: 7, height: 7, borderRadius: '50%',
            background: statusColor,
            boxShadow: online ? `0 0 8px ${statusColor}` : 'none',
            animation: online && trained ? 'statusPulse 1.5s infinite' : 'none',
          }} />
          {statusLabel}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr 1.4fr', gap: 20 }}>
        {/* Model / training meta */}
        <div>
          <div style={PRED_LABEL}>Model</div>
          <div style={{ fontSize: 13, color: '#fff', marginBottom: 2 }}>
            {!online ? 'Backend offline' : payload?.predictor ? 'LSTM checkpoint loaded' : 'No checkpoint yet'}
          </div>
          <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', marginBottom: 10 }}>
            last trained: {lastTrained}
          </div>
          <div style={PRED_KV}><span style={PRED_KV_KEY}>TRAINING SET</span><span style={PRED_KV_VAL}>{meta.count ?? 0} records</span></div>
          <div style={PRED_KV}><span style={PRED_KV_KEY}>SESSION SEED</span><span style={PRED_KV_VAL}>{meta.seed_count ?? 0}</span></div>
        </div>

        {/* Corpus */}
        <div>
          <div style={PRED_LABEL}>Corpus</div>
          <div style={{ fontSize: 26, fontWeight: 700, color: '#00f2ff', fontFamily: 'monospace', marginBottom: 2 }}>
            {totalRecords}
          </div>
          <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', marginBottom: 12 }}>
            records in DB
          </div>
          <div style={PRED_KV}><span style={PRED_KV_KEY}>SNAPSHOTS</span><span style={PRED_KV_VAL}>{corpus.snapshots}</span></div>
          <div style={PRED_KV}><span style={PRED_KV_KEY}>SESSIONS</span><span style={PRED_KV_VAL}>{corpus.sessions}</span></div>
        </div>

        {/* Forecast */}
        <div>
          <div style={PRED_LABEL}>Next-State Forecast</div>
          {f ? (
            <>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 2 }}>
                <span style={{ fontSize: 26, fontWeight: 700, color: valence >= 0 ? '#10b981' : '#ef4444', fontFamily: 'monospace' }}>
                  {valence >= 0 ? '+' : ''}{valence.toFixed(3)}
                </span>
                <span style={{ fontSize: 16, color: f.velocity_valence > 0.01 ? '#10b981' : f.velocity_valence < -0.01 ? '#ef4444' : 'rgba(255,255,255,0.3)' }}>{trend}</span>
                <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', letterSpacing: 1 }}>VALENCE</span>
              </div>
              <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', marginBottom: 8 }}>
                arousal {f.future_arousal.toFixed(2)}
              </div>
              <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
                {f.distress_risk && <RiskBadge active color="#ef4444" label="DISTRESS" />}
                {f.escalation_risk && <RiskBadge active color="#f97316" label="ESCALATION" />}
                {!f.distress_risk && !f.escalation_risk && <RiskBadge active color="#10b981" label="STABLE" />}
              </div>
              <Bar label="Confidence" value={f.confidence} color="#a78bfa" />
            </>
          ) : (
            <div style={{ color: 'rgba(255,255,255,0.25)', fontSize: 12, fontStyle: 'italic', paddingTop: 6, lineHeight: 1.5 }}>
              {!payload
                ? 'Backend offline — forecasts unavailable.'
                : 'No forecast yet — needs a trained checkpoint and ≥2 recent snapshots.'}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

// ── Overview Tab ──────────────────────────────────────────────────────────────
function OverviewTab({ allSignals, trust, personality, emotions, personalityPreset, isOnline, thinking, speaking, listening }) {
  const criticals = allSignals.filter(s => s.severity === 'critical').length;
  const modeInfo  = PERSONALITY_MODES.find(m => m.id === personalityPreset) || PERSONALITY_MODES[0];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <SectionHeader title="System Overview" sub="Real-time FIXV4 cognitive pipeline status" />

      {/* KPI Row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
        <KpiCard label="Backend" value={isOnline ? 'ONLINE' : 'OFFLINE'} color={isOnline ? '#10b981' : '#ef4444'} icon={isOnline ? '🟢' : '🔴'} />
        <KpiCard label="Critical Signals" value={criticals} color={criticals > 0 ? '#ef4444' : '#10b981'} icon="⚠️" />
        <KpiCard label="Trust Score" value={`${Math.round((trust || 0.5) * 100)}%`} color={trust > 0.6 ? '#10b981' : '#ffd93d'} icon="🤝" />
        <KpiCard label="Total Signals" value={allSignals.length} color="#3b82f6" icon="📡" />
      </div>

      {/* Emotion Predictor status (polls /api/emotion/predictor) */}
      <PredictorStatusCard />

      {/* Active Mode + States */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <Card accentColor={modeInfo.color}>
          <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 12 }}>Active Personality Mode</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <span style={{ fontSize: 40 }}>{modeInfo.emoji}</span>
            <div>
              <div style={{ fontSize: 22, fontWeight: 700, color: modeInfo.color, letterSpacing: 1, textTransform: 'uppercase' }}>{modeInfo.label}</div>
              <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.4)', marginTop: 2 }}>{modeInfo.desc}</div>
            </div>
          </div>
        </Card>

        <Card>
          <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 12 }}>Cognitive States</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <StateRow label="Thinking" active={thinking} color="#ffd93d" />
            <StateRow label="Speaking" active={speaking} color="#ff8fa3" />
            <StateRow label="Listening" active={listening} color="#34d399" />
          </div>
        </Card>
      </div>

      {/* Personality axes chart */}
      <Card>
        <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 16 }}>Personality Axes</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 32px' }}>
          <Bar label="Warmth"       value={personality?.warmth || 0}       color="#ffd93d" />
          <Bar label="Energy"       value={personality?.energy || 0}       color="#fb923c" />
          <Bar label="Assertiveness" value={personality?.assertiveness || 0} color="#f43f5e" />
          <Bar label="Formality"    value={personality?.formality || 0}    color="#6bcbef" />
        </div>
      </Card>

      {/* Emotion grid */}
      <Card>
        <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 16 }}>AI Emotion Matrix</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px 24px' }}>
          {Object.entries(emotions || {}).map(([k, v]) => (
            <Bar key={k} label={k} value={v} color="#e91e63" max={1.5} />
          ))}
        </div>
      </Card>

      {/* Recent signals */}
      <Card>
        <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 12 }}>Recent Signal Feed</div>
        {allSignals.length === 0 ? (
          <div style={{ color: 'rgba(255,255,255,0.2)', textAlign: 'center', padding: '40px 0', fontStyle: 'italic', fontSize: 13 }}>
            No signals yet. Awaiting backend connection…
          </div>
        ) : allSignals.slice(0, 8).map((s, i) => (
          <div key={i} style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            padding: '10px 14px', marginBottom: 6,
            background: 'rgba(255,255,255,0.02)',
            borderLeft: `3px solid ${SEV_COLOR[s.severity] || '#444'}`,
            borderRadius: '0 8px 8px 0',
            fontSize: 12,
          }}>
            <div>
              <span style={{ fontWeight: 600, marginRight: 8, color: SEV_COLOR[s.severity] || '#fff', fontSize: 10 }}>[{(s.type || 'signal').toUpperCase()}]</span>
              <span style={{ color: 'rgba(255,255,255,0.8)' }}>{s.payload?.title || 'System Event'}</span>
            </div>
            <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: 11 }}>
              {s.timestamp ? new Date(s.timestamp * 1000).toLocaleTimeString() : '—'}
            </span>
          </div>
        ))}
      </Card>
    </div>
  );
}

function KpiCard({ label, value, color, icon }) {
  return (
    <Card accentColor={color} style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 24, marginBottom: 8 }}>{icon}</div>
      <div style={{ fontSize: 26, fontWeight: 700, color, fontFamily: 'monospace', marginBottom: 4 }}>{value}</div>
      <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: 1 }}>{label}</div>
    </Card>
  );
}

function StateRow({ label, active, color }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 12px', background: active ? `${color}12` : 'rgba(255,255,255,0.02)', borderRadius: 6, border: `1px solid ${active ? `${color}33` : 'transparent'}`, transition: 'all 0.3s' }}>
      <span style={{ fontSize: 12, color: active ? color : 'rgba(255,255,255,0.3)' }}>{label}</span>
      <div style={{ width: 8, height: 8, borderRadius: '50%', background: active ? color : 'rgba(255,255,255,0.1)', boxShadow: active ? `0 0 10px ${color}` : 'none', transition: 'all 0.3s', animation: active ? 'statusPulse 1.5s infinite' : 'none' }} />
    </div>
  );
}

// ── Control Tab ───────────────────────────────────────────────────────────────
function ControlTab({ personalityPreset, autoAdapt, onModeChange, onAutoAdapt, onMemoryWipe, onSessionReset, memoryWiped, isOnline, meetingMode, onToggleMeeting, onSetMeetingWindow, authStatus, onForceMode }) {
  const [windowDraft, setWindowDraft] = React.useState(meetingMode?.base_window || 30);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
      <SectionHeader title="Bi-Directional Control" sub="Push personality overrides and system commands to the cognitive core in real-time" />

      {!isOnline && (
        <div style={{ background: 'rgba(251,146,60,0.1)', border: '1px solid rgba(251,146,60,0.3)', borderRadius: 10, padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 10, fontSize: 12, color: '#fb923c' }}>
          ⚠️ Backend offline — commands will be queued via BroadcastChannel and applied when reconnected
        </div>
      )}

      {/* Personality Selector */}
      <Card>
        <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 16 }}>Personality Mode Override</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          {PERSONALITY_MODES.map(mode => {
            const active = personalityPreset === mode.id;
            return (
              <button
                key={mode.id}
                onClick={() => onModeChange(mode.id)}
                style={{
                  display: 'flex', flexDirection: 'column', alignItems: 'flex-start',
                  gap: 4, padding: '14px 16px', borderRadius: 10, cursor: 'pointer',
                  background: active ? `color-mix(in srgb, ${mode.color} 14%, transparent)` : 'rgba(255,255,255,0.03)',
                  border: `1px solid ${active ? mode.color : 'rgba(255,255,255,0.08)'}`,
                  boxShadow: active ? `0 0 18px ${mode.color}30` : 'none',
                  color: '#fff', textAlign: 'left',
                  transition: 'all 0.2s ease',
                }}
                onMouseOver={e => { if (!active) { e.currentTarget.style.borderColor = mode.color; e.currentTarget.style.background = `${mode.color}0d`; } }}
                onMouseOut={e => { if (!active) { e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)'; e.currentTarget.style.background = 'rgba(255,255,255,0.03)'; } }}
              >
                <span style={{ fontSize: 22 }}>{mode.emoji}</span>
                <span style={{ fontSize: 12, fontWeight: 700, color: active ? mode.color : '#fff', textTransform: 'uppercase', letterSpacing: 0.5 }}>{mode.label}</span>
                <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)', lineHeight: 1.4 }}>{mode.desc}</span>
              </button>
            );
          })}
        </div>
      </Card>

      {/* Auto-Adapt + System Controls */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <Card>
          <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 16 }}>Autonomous Adaptation</div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px', background: 'rgba(255,255,255,0.03)', borderRadius: 10, border: `1px solid ${autoAdapt ? 'rgba(16,185,129,0.3)' : 'rgba(255,255,255,0.07)'}` }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: '#fff', marginBottom: 3 }}>AUTO-ADAPT</div>
              <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)' }}>Allow Aariya to nudge her own personality ±0.05/session based on rapport</div>
            </div>
            <ToggleSwitch checked={autoAdapt} onChange={onAutoAdapt} color="#10b981" />
          </div>
        </Card>

        <Card>
          <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 16 }}>System Commands</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <ControlBtn onClick={onMemoryWipe} danger label={memoryWiped ? '✓ Memory Cleared!' : '🗑 Wipe Working Memory'} disabled={memoryWiped} />
            <ControlBtn onClick={onSessionReset} label="🔄 Reset Session" />
          </div>
        </Card>
      </div>

      {/* ── Authority Layer (laptop-only, server-executed) ── */}
      <Card accentColor="#a78bfa">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
          <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, textTransform: 'uppercase' }}>🔐 Authority Layer</div>
          <span style={{
            fontSize: 9, fontWeight: 800, letterSpacing: 1, padding: '2px 8px', borderRadius: 4,
            background: 'rgba(167,139,250,0.15)', border: '1px solid rgba(167,139,250,0.4)',
            color: '#a78bfa', whiteSpace: 'nowrap',
          }}>LAPTOP ONLY</span>
        </div>
        <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.35)', marginBottom: 14 }}>
          Destructive / identity-mutating commands are <b style={{ color: '#f87171' }}>denied</b> on the mobile
          channel — they are <b style={{ color: '#a78bfa' }}>executed here</b>, on the laptop's /ws/brain_metrics
          socket, and broadcast to every surface. Changes persist server-side.
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div>
            <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 10 }}>Force Behaviour Mode</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {['focus', 'relax', 'guard', 'chat'].map(mode => (
                  <button
                    key={mode}
                    onClick={() => onForceMode(mode)}
                    style={{
                      padding: '6px 12px', borderRadius: 6, cursor: 'pointer',
                      fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.8,
                      background: 'rgba(167,139,250,0.08)',
                      border: '1px solid rgba(167,139,250,0.3)', color: '#a78bfa',
                      transition: 'all 0.2s',
                    }}
                    onMouseOver={e => { e.currentTarget.style.background = 'rgba(167,139,250,0.2)'; e.currentTarget.style.borderColor = '#a78bfa'; }}
                    onMouseOut={e => { e.currentTarget.style.background = 'rgba(167,139,250,0.08)'; e.currentTarget.style.borderColor = 'rgba(167,139,250,0.3)'; }}
                  >{mode}</button>
                ))}
              </div>
            </div>
          </div>

          <div>
            <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 10 }}>Last Server Ack</div>
            <div style={{
              padding: '12px 14px', borderRadius: 8, fontSize: 12,
              background: authStatus
                ? (authStatus.ok ? 'rgba(16,185,129,0.08)' : 'rgba(239,68,68,0.08)')
                : 'rgba(255,255,255,0.02)',
              border: `1px solid ${authStatus ? (authStatus.ok ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)') : 'rgba(255,255,255,0.06)'}`,
              fontFamily: "'JetBrains Mono', monospace",
              color: authStatus ? (authStatus.ok ? '#34d399' : '#f87171') : 'rgba(255,255,255,0.3)',
            }}>
              {!authStatus
                ? '— no command sent yet —'
                : `${authStatus.ok ? '✓' : '✗'} ${authStatus.action}${authStatus.preset ? ` → ${authStatus.preset}` : ''}${authStatus.mode ? ` → ${authStatus.mode}` : ''}${authStatus.error ? ` (${authStatus.error})` : ''}${authStatus.at ? ` @ ${new Date(authStatus.at).toLocaleTimeString()}` : ''}`}
            </div>
            <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.25)', marginTop: 8 }}>
              Wipe Memory & Personality Mode buttons above execute on this same channel.
            </div>
          </div>
        </div>
      </Card>

      {/* ── Meeting Mode Panel ── */}
      <Card accentColor={meetingMode?.active ? '#ffd93d' : undefined}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 3 }}>Meeting Mode</div>
            <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.35)' }}>Ambient QoS — Aariya only speaks when directly addressed</div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: meetingMode?.active ? '#ffd93d' : 'rgba(255,255,255,0.3)', letterSpacing: 1, textTransform: 'uppercase' }}>
              {meetingMode?.active ? 'ACTIVE' : 'OFF'}
            </span>
            <ToggleSwitch checked={!!meetingMode?.active} onChange={onToggleMeeting} color="#ffd93d" />
          </div>
        </div>

        {/* Speaker count + window info */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginBottom: 16 }}>
          <div style={{ textAlign: 'center', padding: '10px 8px', borderRadius: 8, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)' }}>
            <div style={{ fontSize: 24, fontWeight: 700, color: '#ffd93d', fontFamily: 'monospace' }}>{meetingMode?.speaker_count ?? 1}</div>
            <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', textTransform: 'uppercase', letterSpacing: 1 }}>Est. Speakers</div>
          </div>
          <div style={{ textAlign: 'center', padding: '10px 8px', borderRadius: 8, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)' }}>
            <div style={{ fontSize: 24, fontWeight: 700, color: '#00f2ff', fontFamily: 'monospace' }}>{Math.round(meetingMode?.direct_address_window ?? 30)}s</div>
            <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', textTransform: 'uppercase', letterSpacing: 1 }}>Follow-up Window</div>
          </div>
          <div style={{ textAlign: 'center', padding: '10px 8px', borderRadius: 8, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)' }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#ff8fa3', fontFamily: 'monospace', wordBreak: 'break-all' }}>
              {(meetingMode?.ai_names || ['aariya']).join(', ')}
            </div>
            <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', textTransform: 'uppercase', letterSpacing: 1 }}>Name Triggers</div>
          </div>
        </div>

        {/* Base window slider */}
        <div style={{ padding: '10px 14px', background: 'rgba(255,255,255,0.02)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.05)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: 11, color: 'rgba(255,255,255,0.4)' }}>
            <span>Base follow-up window</span>
            <span style={{ color: '#00f2ff', fontWeight: 700, fontFamily: 'monospace' }}>{windowDraft}s</span>
          </div>
          <input
            type="range" min={10} max={120} step={5}
            value={windowDraft}
            onChange={e => setWindowDraft(Number(e.target.value))}
            onMouseUp={() => onSetMeetingWindow?.(windowDraft)}
            onTouchEnd={() => onSetMeetingWindow?.(windowDraft)}
            style={{ width: '100%', accentColor: '#ffd93d', cursor: 'pointer' }}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: 'rgba(255,255,255,0.2)' }}>
            <span>10s (strict)</span><span>120s (relaxed)</span>
          </div>
        </div>
      </Card>

      {/* Trust explainer */}
      <Card accentColor="#6bcbef">
        <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 14 }}>Trust Tier Reference</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10 }}>
          {[
            { range: '0–20%', tier: 'DEFENSIVE', color: '#ef4444', desc: 'Minimal responses' },
            { range: '20–40%', tier: 'GUARDED',   color: '#f97316', desc: 'Cautious curiosity' },
            { range: '40–60%', tier: 'NEUTRAL',   color: '#ffd93d', desc: 'Standard companion' },
            { range: '60–85%', tier: 'WARM',      color: '#10b981', desc: 'Expressive & Playful' },
            { range: '85–100%',tier: 'INTIMATE',  color: '#a78bfa', desc: 'Full transparency' },
          ].map(t => (
            <div key={t.tier} style={{ textAlign: 'center', padding: '10px 8px', borderRadius: 8, background: `${t.color}10`, border: `1px solid ${t.color}30` }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: t.color, marginBottom: 3 }}>{t.tier}</div>
              <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', marginBottom: 3 }}>{t.range}</div>
              <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.4)', lineHeight: 1.4 }}>{t.desc}</div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function ToggleSwitch({ checked, onChange, color = '#00f2ff' }) {
  return (
    <div
      onClick={onChange}
      style={{
        width: 48, height: 26, borderRadius: 13, cursor: 'pointer',
        background: checked ? color : 'rgba(255,255,255,0.1)',
        position: 'relative', transition: 'background 0.25s',
        flexShrink: 0,
      }}
    >
      <div style={{
        position: 'absolute', top: 3, left: checked ? 26 : 3,
        width: 20, height: 20, borderRadius: '50%',
        background: '#fff', transition: 'left 0.25s',
        boxShadow: '0 2px 4px rgba(0,0,0,0.3)',
      }} />
    </div>
  );
}

function ControlBtn({ onClick, label, danger, disabled }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: '10px 16px', borderRadius: 8, cursor: disabled ? 'not-allowed' : 'pointer',
        fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.8,
        transition: 'all 0.2s', opacity: disabled ? 0.6 : 1,
        background: danger ? 'rgba(239,68,68,0.08)' : 'rgba(255,255,255,0.04)',
        border: `1px solid ${danger ? 'rgba(239,68,68,0.3)' : 'rgba(255,255,255,0.12)'}`,
        color: danger ? '#f87171' : '#fff',
      }}
      onMouseOver={e => {
        if (!disabled) {
          e.currentTarget.style.background = danger ? 'rgba(239,68,68,0.18)' : 'rgba(0,242,255,0.1)';
          e.currentTarget.style.borderColor = danger ? '#ef4444' : '#00f2ff';
        }
      }}
      onMouseOut={e => {
        e.currentTarget.style.background = danger ? 'rgba(239,68,68,0.08)' : 'rgba(255,255,255,0.04)';
        e.currentTarget.style.borderColor = danger ? 'rgba(239,68,68,0.3)' : 'rgba(255,255,255,0.12)';
      }}
    >{label}</button>
  );
}

// ── Signals Tab ───────────────────────────────────────────────────────────────
function SignalsTab({ signals, filter, onFilter, selected, onSelect, onAck, onResolve }) {
  const filters = ['all', 'critical', 'info', 'bug', 'telemetry'];

  return (
    <div style={{ display: 'flex', height: '100%', gap: 0 }}>
      {/* Main list */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0, marginRight: selected ? 420 : 0, transition: 'margin 0.35s' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <SectionHeader title="Signals & Events" sub="5-level severity — click any row to inspect" />
          <div style={{ display: 'flex', gap: 4, background: 'rgba(255,255,255,0.03)', padding: 3, borderRadius: 8, border: '1px solid rgba(255,255,255,0.05)' }}>
            {filters.map(f => (
              <button key={f} onClick={() => onFilter(f)} style={{
                padding: '4px 10px', borderRadius: 5, border: 'none', cursor: 'pointer', fontSize: 10, fontWeight: 700, letterSpacing: 0.8, textTransform: 'uppercase',
                background: filter === f ? '#00f2ff' : 'transparent',
                color: filter === f ? '#000' : 'rgba(255,255,255,0.4)',
                transition: 'all 0.2s',
              }}>{f}</button>
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {signals.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '60px 0', color: 'rgba(255,255,255,0.2)', fontStyle: 'italic' }}>No signals for this filter</div>
          ) : signals.map((s, i) => (
            <div key={s.id || i}
              onClick={() => onSelect(selected?.id === s.id ? null : s)}
              style={{
                display: 'grid', gridTemplateColumns: '72px 80px 1fr 120px 80px',
                alignItems: 'center', padding: '12px 16px',
                background: selected?.id === s.id ? 'rgba(0,242,255,0.06)' : 'rgba(255,255,255,0.025)',
                borderLeft: `3px solid ${SEV_COLOR[s.severity] || '#444'}`,
                borderRadius: '0 8px 8px 0', cursor: 'pointer',
                border: `1px solid ${selected?.id === s.id ? 'rgba(0,242,255,0.25)' : 'rgba(255,255,255,0.04)'}`,
                transition: 'all 0.2s',
              }}
              onMouseOver={e => { if (selected?.id !== s.id) e.currentTarget.style.background = 'rgba(0,242,255,0.04)'; }}
              onMouseOut={e => { if (selected?.id !== s.id) e.currentTarget.style.background = 'rgba(255,255,255,0.025)'; }}
            >
              <span style={{ color: SEV_COLOR[s.severity], fontSize: 10, fontWeight: 700 }}>{(s.severity || 'info').toUpperCase()}</span>
              <span style={{ color: 'rgba(255,255,255,0.35)', fontSize: 10 }}>{
                s.timestamp ? new Date(s.timestamp * 1000).toLocaleTimeString() : '—'
              }</span>
              <span style={{ fontSize: 12, color: '#fff', fontWeight: 500 }}>{s.payload?.title || s.type || 'Signal'}</span>
              <span style={{ fontSize: 10, color: '#a78bfa' }}>{s.source?.system || '—'}</span>
              <div style={{ display: 'flex', gap: 4 }}>
                {s.status === 'new' && (
                  <>
                    <SmBtn onClick={(e) => { e.stopPropagation(); onAck(s.id); }} label="ACK" />
                    <SmBtn onClick={(e) => { e.stopPropagation(); onResolve(s.id); }} label="OK" color="#10b981" />
                  </>
                )}
                {s.status !== 'new' && <span style={{ fontSize: 9, color: 'rgba(255,255,255,0.2)', textTransform: 'capitalize' }}>{s.status}</span>}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Inspector panel */}
      {selected && (
        <div style={{
          position: 'fixed', top: 112, right: 0, bottom: 0, width: 400,
          background: 'rgba(10,12,22,0.96)', backdropFilter: 'blur(20px)',
          borderLeft: '1px solid rgba(0,242,255,0.2)',
          boxShadow: '-20px 0 50px rgba(0,0,0,0.6)',
          display: 'flex', flexDirection: 'column', zIndex: 200,
          animation: 'inspectorSlideIn 0.35s cubic-bezier(0.16,1,0.3,1)',
        }}>
          <div style={{ padding: '20px 24px', borderBottom: '1px solid rgba(255,255,255,0.07)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: '#00f2ff', letterSpacing: 1, textTransform: 'uppercase' }}>Signal Inspector</div>
              <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', fontFamily: 'monospace', marginTop: 2 }}>#{selected.id?.toString().slice(-8) || '00000000'}</div>
            </div>
            <button onClick={() => onSelect(null)} style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.4)', fontSize: 22, cursor: 'pointer', transition: 'color 0.2s' }}
              onMouseOver={e => e.currentTarget.style.color = '#ef4444'}
              onMouseOut={e => e.currentTarget.style.color = 'rgba(255,255,255,0.4)'}
            >✕</button>
          </div>
          <div style={{ flex: 1, overflowY: 'auto', padding: 24, display: 'flex', flexDirection: 'column', gap: 20 }}>
            <div style={{ padding: 16, borderRadius: 10, background: `${SEV_COLOR[selected.severity] || '#444'}12`, border: `1px solid ${SEV_COLOR[selected.severity] || '#444'}30` }}>
              <div style={{ fontSize: 10, color: SEV_COLOR[selected.severity], fontWeight: 700, letterSpacing: 1.5, marginBottom: 8 }}>{(selected.severity || 'info').toUpperCase()} SEVERITY</div>
              <div style={{ fontSize: 15, fontWeight: 600, color: '#fff', marginBottom: 4 }}>{selected.payload?.title || selected.type || 'Signal'}</div>
              <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.5)', lineHeight: 1.6 }}>{selected.payload?.description || 'No additional details.'}</div>
            </div>
            <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 10, padding: 16, border: '1px solid rgba(255,255,255,0.05)' }}>
              <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, marginBottom: 12, textTransform: 'uppercase' }}>Metadata</div>
              {[
                ['Type', selected.type],
                ['Source', selected.source?.system || '—'],
                ['Status', selected.status],
                ['Time', selected.timestamp ? new Date(selected.timestamp * 1000).toLocaleString() : '—'],
              ].map(([k, v]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid rgba(255,255,255,0.04)', fontSize: 12 }}>
                  <span style={{ color: 'rgba(255,255,255,0.35)' }}>{k}</span>
                  <span style={{ color: '#fff', fontWeight: 500 }}>{v}</span>
                </div>
              ))}
            </div>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, textTransform: 'uppercase' }}>Raw Payload</div>
              </div>
              <pre style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, background: '#000', padding: 14, borderRadius: 10, border: '1px solid rgba(255,255,255,0.05)', color: '#82ca9d', overflowX: 'auto', margin: 0 }}>
                {JSON.stringify(selected.payload || {}, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SmBtn({ onClick, label, color = '#6bcbef' }) {
  return (
    <button onClick={onClick} style={{
      background: `${color}18`, border: `1px solid ${color}44`,
      color, borderRadius: 4, padding: '3px 8px',
      fontSize: 9, fontWeight: 700, cursor: 'pointer', letterSpacing: 0.5,
    }}>{label}</button>
  );
}

// ── Event Log Tab ─────────────────────────────────────────────────────────────
function EventLogTab({ log, onClear, isOnline }) {
  const logRef = useRef(null);
  const [paused, setPaused] = useState(false);
  const [tagFilter, setTagFilter] = useState('ALL');

  useEffect(() => {
    if (!paused && logRef.current) {
      logRef.current.scrollTop = 0;
    }
  }, [log, paused]);

  const tags = ['ALL', 'SENSORS', 'SWARM', 'BRAIN', 'LLM', 'VOICE', 'SYSTEM'];
  const filtered = tagFilter === 'ALL' ? log : log.filter(l => l.tag === tagFilter);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <SectionHeader title="Live Event Log" sub={`${isOnline ? '🟢 Live feed' : '🔴 Demo mode'} — real-time cognitive pipeline trace`} />
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => setPaused(!paused)} style={{
            background: paused ? 'rgba(251,146,60,0.15)' : 'rgba(255,255,255,0.05)',
            border: `1px solid ${paused ? '#fb923c' : 'rgba(255,255,255,0.1)'}`,
            color: paused ? '#fb923c' : 'rgba(255,255,255,0.5)',
            borderRadius: 6, padding: '6px 14px', cursor: 'pointer', fontSize: 11, fontWeight: 600,
          }}>{paused ? '▶ Resume' : '⏸ Pause'}</button>
          <button onClick={onClear} style={{
            background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)',
            color: '#f87171', borderRadius: 6, padding: '6px 14px', cursor: 'pointer', fontSize: 11, fontWeight: 600,
          }}>🗑 Clear</button>
        </div>
      </div>

      {/* Tag filter */}
      <div style={{ display: 'flex', gap: 4 }}>
        {tags.map(t => (
          <button key={t} onClick={() => setTagFilter(t)} style={{
            padding: '4px 10px', borderRadius: 5, border: 'none', cursor: 'pointer',
            fontSize: 9, fontWeight: 700, letterSpacing: 1, textTransform: 'uppercase',
            background: tagFilter === t ? (LOG_TAG_COLOR[t] || '#00f2ff') : 'rgba(255,255,255,0.04)',
            color: tagFilter === t ? '#000' : (LOG_TAG_COLOR[t] || 'rgba(255,255,255,0.35)'),
            transition: 'all 0.2s',
          }}>{t}</button>
        ))}
      </div>

      {/* Log entries */}
      <div
        ref={logRef}
        style={{
          flex: 1, overflowY: 'auto', background: '#000',
          borderRadius: 12, border: '1px solid rgba(255,255,255,0.06)',
          padding: 14, fontFamily: "'JetBrains Mono', monospace", fontSize: 11,
        }}
      >
        {filtered.length === 0 ? (
          <div style={{ color: 'rgba(255,255,255,0.2)', textAlign: 'center', marginTop: 40, fontStyle: 'italic' }}>
            {isOnline ? 'Waiting for events…' : 'Demo events loading…'}
          </div>
        ) : filtered.map((entry, i) => {
          const tagColor = LOG_TAG_COLOR[entry.tag] || '#94a3b8';
          const ts = entry.ts
            ? new Date(entry.ts * 1000).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
            : '——:——:——';

          return (
            <div key={entry.id || i} style={{
              display: 'flex', alignItems: 'flex-start', gap: 8,
              padding: '4px 0', borderBottom: '1px solid rgba(255,255,255,0.03)',
              animation: i === 0 ? 'logFadeIn 0.4s ease' : 'none',
            }}>
              <span style={{ color: '#444', flexShrink: 0, lineHeight: '16px' }}>{ts}</span>
              <span style={{
                color: tagColor, background: `${tagColor}18`, border: `1px solid ${tagColor}30`,
                borderRadius: 3, padding: '0 5px', fontSize: 9, fontWeight: 700, letterSpacing: 1,
                flexShrink: 0, lineHeight: '16px', marginTop: 1,
              }}>{entry.tag}</span>
              <span style={{ color: entry.severity === 'critical' ? '#ef4444' : entry.severity === 'high' ? '#f97316' : 'rgba(255,255,255,0.7)', lineHeight: '16px', flex: 1 }}>
                {entry.text}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// 3D PERSONALITY SPACE TAB
// Perspective-projected Canvas2D. No Three.js dependency.
// X = Valence (-1 → +1), Y = Arousal (0 → 1), Z = Trust (0 → 1)
// ═══════════════════════════════════════════════════════════════════════════════

function PersonalitySpace3DTab({ trust, userEmotion, personality, personalityPreset }) {
  const canvasRef = useRef(null);
  const animRef   = useRef(null);
  const trailRef  = useRef([]);
  const angleRef  = useRef(0);
  const particlesRef = useRef([]);

  const val = userEmotion?.valence ?? 0;
  const aro = userEmotion?.arousal ?? 0;
  const tru = trust ?? 0.5;
  const modeInfo = PERSONALITY_MODES.find(m => m.id === personalityPreset) || PERSONALITY_MODES[0];

  useEffect(() => {
    if (particlesRef.current.length === 0) {
      particlesRef.current = Array.from({ length: 40 }, () => ({
        x: (Math.random() - 0.5) * 3,
        y: (Math.random() - 0.5) * 3,
        z: (Math.random() - 0.5) * 3,
        speed: Math.random() * 0.005 + 0.002,
        offset: Math.random() * Math.PI * 2
      }));
    }
  }, []);

  useEffect(() => {
    trailRef.current = [...trailRef.current, { x: val, y: aro, z: tru }].slice(-40);
  }, [val, aro, tru]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    // Advanced 3D projection with Yaw and Pitch (tilt)
    function project(x, y, z, angle, cx, cy) {
      // Yaw rotation
      const sinA = Math.sin(angle), cosA = Math.cos(angle);
      const rx = x * cosA - z * sinA;
      const rz = x * sinA + z * cosA;
      
      // Pitch rotation (tilt slightly down)
      const tilt = 0.35;
      const sinT = Math.sin(tilt), cosT = Math.cos(tilt);
      const ry = y * cosT - rz * sinT;
      const rz2 = y * sinT + rz * cosT;
      
      const fov = 400;
      const distance = 450;
      const scale = 220;
      
      const denominator = fov + rz2 * scale + distance;
      const depth = denominator > 0 ? fov / denominator : 0;
      return { 
        sx: cx + rx * depth * scale, 
        sy: cy - ry * depth * scale, 
        depth,
        opacity: Math.max(0, Math.min(1, depth * 1.5))
      };
    }

    function draw() {
      const W = canvas.width, H = canvas.height;
      const cx = W / 2, cy = H / 2 + 30;
      const angle = angleRef.current;

      // Premium dark background with slight radial glow in center
      ctx.fillStyle = '#030305';
      ctx.fillRect(0, 0, W, H);
      
      const bgGlow = ctx.createRadialGradient(cx, cy, 0, cx, cy, W/1.5);
      bgGlow.addColorStop(0, 'rgba(120, 100, 200, 0.05)');
      bgGlow.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = bgGlow;
      ctx.fillRect(0, 0, W, H);

      // Draw Grid Floor (at y = -1.2)
      ctx.lineWidth = 1;
      const floorY = -1.2;
      for (let i = -2; i <= 2; i += 0.4) {
        // Horizontal lines
        const p1 = project(-2, floorY, i, angle, cx, cy);
        const p2 = project(2, floorY, i, angle, cx, cy);
        ctx.beginPath(); ctx.moveTo(p1.sx, p1.sy); ctx.lineTo(p2.sx, p2.sy);
        const gradX = ctx.createLinearGradient(p1.sx, p1.sy, p2.sx, p2.sy);
        gradX.addColorStop(0, 'rgba(255,255,255,0)');
        gradX.addColorStop(0.5, `rgba(255,255,255,${0.15 * p1.opacity})`);
        gradX.addColorStop(1, 'rgba(255,255,255,0)');
        ctx.strokeStyle = gradX;
        ctx.stroke();

        // Vertical lines
        const p3 = project(i, floorY, -2, angle, cx, cy);
        const p4 = project(i, floorY, 2, angle, cx, cy);
        ctx.beginPath(); ctx.moveTo(p3.sx, p3.sy); ctx.lineTo(p4.sx, p4.sy);
        const gradZ = ctx.createLinearGradient(p3.sx, p3.sy, p4.sx, p4.sy);
        gradZ.addColorStop(0, 'rgba(255,255,255,0)');
        gradZ.addColorStop(0.5, `rgba(255,255,255,${0.15 * p3.opacity})`);
        gradZ.addColorStop(1, 'rgba(255,255,255,0)');
        ctx.strokeStyle = gradZ;
        ctx.stroke();
      }

      // Floating Ambient Particles
      particlesRef.current.forEach(pt => {
        pt.y += Math.sin(Date.now() * pt.speed + pt.offset) * 0.005;
        const pp = project(pt.x, pt.y, pt.z, angle, cx, cy);
        if (pp.opacity > 0) {
          ctx.beginPath();
          ctx.arc(pp.sx, pp.sy, 1.5 * pp.depth, 0, Math.PI*2);
          ctx.fillStyle = `rgba(167,139,250,${pp.opacity * 0.4})`;
          ctx.fill();
        }
      });

      // 3D Axes
      [
        { from: [-1.5,0,0], to: [1.5,0,0],   color: '#ef4444', label: 'Valence', lPos: [1.7,0,0] },
        { from: [0,-1,0], to: [0,1.5,0], color: '#ffd93d', label: 'Arousal', lPos: [0,1.7,0] },
        { from: [0,0,-1.5], to: [0,0,1.5],   color: '#6bcbef', label: 'Trust',   lPos: [0,0,1.7] },
      ].forEach(({ from, to, color, label, lPos }) => {
        const p1 = project(...from, angle, cx, cy);
        const p2 = project(...to,   angle, cx, cy);
        ctx.beginPath(); ctx.moveTo(p1.sx, p1.sy); ctx.lineTo(p2.sx, p2.sy);
        ctx.strokeStyle = color + '66'; ctx.lineWidth = 1; ctx.stroke();
        
        const lp = project(...lPos, angle, cx, cy);
        if (lp.depth > 0.3) {
          ctx.fillStyle = color; ctx.font = '700 11px Inter,sans-serif';
          ctx.textAlign = 'center'; ctx.fillText(label, lp.sx, lp.sy);
        }
      });

      // Core Identity (Complex geometric rings)
      const core = { x:0, y:0.5, z:0.5 };
      const cp = project(core.x, core.y, core.z, angle, cx, cy);
      
      // Outer aura
      const aura = ctx.createRadialGradient(cp.sx, cp.sy, 0, cp.sx, cp.sy, 40 * cp.depth);
      aura.addColorStop(0, 'rgba(255,143,163,0.3)'); 
      aura.addColorStop(1, 'rgba(255,143,163,0)');
      ctx.beginPath(); ctx.arc(cp.sx, cp.sy, 40*cp.depth, 0, Math.PI*2);
      ctx.fillStyle = aura; ctx.fill();

      // Mutable orbit rings
      const tNow = Date.now() * 0.001;
      [0, Math.PI/2, Math.PI/4].forEach((offset, idx) => {
        ctx.beginPath();
        for (let i=0; i<=40; i++) {
          const t = (i/40)*Math.PI*2;
          const radius = 0.25;
          let ox = Math.cos(t)*radius;
          let oz = Math.sin(t)*radius;
          let oy = Math.sin(t + tNow + offset) * 0.1; // dynamic tilt
          if (idx === 1) [ox, oy] = [oy, ox];
          
          const op = project(core.x+ox, core.y+oy, core.z+oz, angle, cx, cy);
          i===0 ? ctx.moveTo(op.sx, op.sy) : ctx.lineTo(op.sx, op.sy);
        }
        ctx.strokeStyle = `rgba(167,139,250,${0.2 + idx*0.1})`; 
        ctx.lineWidth = 1;
        ctx.stroke();
      });

      // Solid core
      ctx.beginPath(); ctx.arc(cp.sx, cp.sy, 6*cp.depth, 0, Math.PI*2);
      ctx.fillStyle = '#ff8fa3'; ctx.shadowColor = '#ff8fa3'; ctx.shadowBlur = 10;
      ctx.fill(); ctx.shadowBlur = 0;
      
      // Continuous Glowing Trail
      if (trailRef.current.length > 0) {
        ctx.beginPath();
        for(let i=0; i<trailRef.current.length; i++) {
          const pt = trailRef.current[i];
          const tp = project(pt.x, pt.y, pt.z, angle, cx, cy);
          if (i === 0) ctx.moveTo(tp.sx, tp.sy);
          else ctx.lineTo(tp.sx, tp.sy);
        }
        ctx.strokeStyle = 'rgba(0, 242, 255, 0.4)';
        ctx.lineWidth = 2;
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';
        ctx.stroke();

        // Trail nodes
        trailRef.current.forEach((pt, i) => {
          const a = (i/trailRef.current.length) * 0.8;
          const tp = project(pt.x, pt.y, pt.z, angle, cx, cy);
          ctx.beginPath(); ctx.arc(tp.sx, tp.sy, Math.max(1, 3*tp.depth*a), 0, Math.PI*2);
          ctx.fillStyle = `rgba(0,242,255,${a})`; ctx.fill();
        });
      }

      // Live "NOW" Dot
      const lp = project(val, aro, tru, angle, cx, cy);
      
      // Grounding line linking the live dot to the floor
      const groundPt = project(val, floorY, tru, angle, cx, cy);
      ctx.beginPath(); ctx.moveTo(lp.sx, lp.sy); ctx.lineTo(groundPt.sx, groundPt.sy);
      ctx.strokeStyle = 'rgba(255,255,255,0.2)'; 
      ctx.setLineDash([3, 4]); ctx.lineWidth = 1; ctx.stroke(); ctx.setLineDash([]);
      
      // Floor circle where drop line hits
      ctx.beginPath();
      // approximate oval for floor shadow
      ctx.ellipse(groundPt.sx, groundPt.sy, 12 * groundPt.depth, 6 * groundPt.depth, 0, 0, Math.PI*2);
      ctx.fillStyle = modeInfo.color + '44'; ctx.fill();

      // Dynamic intense glow
      const glowScale = 1 + Math.sin(tNow * 4) * 0.15;
      const glow = ctx.createRadialGradient(lp.sx, lp.sy, 0, lp.sx, lp.sy, 45 * lp.depth * glowScale);
      glow.addColorStop(0, modeInfo.color+'99'); 
      glow.addColorStop(1, modeInfo.color+'00');
      ctx.beginPath(); ctx.arc(lp.sx, lp.sy, 45*lp.depth*glowScale, 0, Math.PI*2); 
      ctx.fillStyle = glow; ctx.fill();
      
      // Bright core
      ctx.beginPath(); ctx.arc(lp.sx, lp.sy, 6*lp.depth, 0, Math.PI*2);
      ctx.fillStyle = '#fff'; ctx.shadowColor = modeInfo.color; ctx.shadowBlur = 20;
      ctx.fill(); ctx.shadowBlur = 0;
      
      // Callout Label
      ctx.fillStyle = '#fff'; ctx.font = '800 12px Inter,sans-serif';
      ctx.textAlign = 'center'; 
      ctx.fillText('NOW', lp.sx, lp.sy - (12 * lp.depth) - 10);

      angleRef.current -= 0.002; // Slow elegant rotation
      animRef.current = requestAnimationFrame(draw);
    }

    animRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(animRef.current);
  }, [val, aro, tru, modeInfo]);

  return (
    <div style={{ display:'flex', flexDirection:'column', gap:20, height:'100%' }}>
      <SectionHeader title="3D Personality Space"
        sub="Live high-dimensional affect vector projecting Valence, Arousal, and Trust" />
      <div style={{ display:'grid', gridTemplateColumns:'1fr 340px', gap:24, flex:1, minHeight:0 }}>
        
        {/* PREMIUM CANVAS WRAPPER */}
        <div style={{ 
          borderRadius: 24, 
          border: '1px solid rgba(255,255,255,0.08)', 
          background: 'radial-gradient(circle at 50% 50%, #151520 0%, #050508 100%)',
          boxShadow: 'inset 0 0 60px rgba(0,0,0,0.5), 0 8px 32px rgba(0,0,0,0.4)',
          overflow: 'hidden', 
          position: 'relative' 
        }}>
          <canvas ref={canvasRef} width={800} height={560} style={{ width:'100%', height:'100%', display:'block' }} />
          
          {/* TOP-LEFT GLASSMORPHISM OVERLAY (HUD) */}
          <div style={{
            position: 'absolute', top: 20, left: 20,
            background: 'rgba(20, 20, 25, 0.4)',
            backdropFilter: 'blur(12px)',
            WebkitBackdropFilter: 'blur(12px)',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: 16,
            padding: '16px 20px',
            display: 'flex', flexDirection: 'column', gap: 12,
            boxShadow: '0 4px 24px rgba(0,0,0,0.2)'
          }}>
            <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)', letterSpacing: 1.5, fontWeight: 600 }}>TENSOR STATE</div>
            {[
              { label: 'VALENCE', value: val, color: '#ef4444' },
              { label: 'AROUSAL', value: aro, color: '#ffd93d' },
              { label: 'TRUST',   value: tru, color: '#6bcbef' }
            ].map(ax => (
              <div key={ax.label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 24 }}>
                <span style={{ color: ax.color, fontSize: 11, fontWeight: 700, letterSpacing: 1 }}>{ax.label}</span>
                <span style={{ color: '#fff', fontSize: 12, fontFamily: 'JetBrains Mono, monospace' }}>{Number(ax.value).toFixed(3)}</span>
              </div>
            ))}
          </div>

          {/* TOP-RIGHT MODE BADGE */}
          <div style={{
            position: 'absolute', top: 20, right: 20,
            background: `rgba(${modeInfo.color.match(/\w\w/g).map(x=>parseInt(x,16)).join(',')}, 0.15)`,
            backdropFilter: 'blur(8px)',
            border: `1px solid ${modeInfo.color}40`,
            borderRadius: 30,
            padding: '6px 16px',
            color: modeInfo.color,
            fontSize: 11, fontWeight: 700, letterSpacing: 1,
            boxShadow: `0 0 20px ${modeInfo.color}20`
          }}>
            MODE: {modeInfo.label.toUpperCase()}
          </div>
          
          <div style={{ position:'absolute', bottom:16, right:20, fontSize:9, color:'rgba(255,255,255,0.25)', letterSpacing:2 }}>
            AUTO-METRIC PROJECTION · NEURAL SPACE V4
          </div>
        </div>

        {/* RIGHT METRICS PANEL */}
        <div style={{ display:'flex', flexDirection:'column', gap:16, paddingRight: 4 }}>
          <Card>
            <div style={{ fontSize:10, color:'rgba(255,255,255,0.4)', letterSpacing:1.5, textTransform:'uppercase', marginBottom:16, fontWeight:600 }}>Current Imprint</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <Bar label="Valence (Pleasure)" value={val} color="#ef4444" min={-1} max={1} />
              <Bar label="Arousal (Energy)"   value={aro} color="#ffd93d" />
              <Bar label="Trust (Bond)"       value={tru} color="#6bcbef" />
            </div>
          </Card>

          <Card>
            <div style={{ fontSize:10, color:'rgba(255,255,255,0.4)', letterSpacing:1.5, textTransform:'uppercase', marginBottom:16, fontWeight:600 }}>Vector Legend</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {[
                { dot:'#ff8fa3', label:'Core Identity',   desc:'Rigid personality anchor' },
                { dot:'#a78bfa', label:'Mutable Surface', desc:'Adaptive conversational orbit' },
                { dot:modeInfo.color, label:'Neural Spark',  desc:'Active emotional coordinate' },
                { dot:'#00f2ff', label:'Affect Trail',    desc:'Historical reaction pathway' },
              ].map(({ dot, label, desc }) => (
                <div key={label} style={{ display:'flex', alignItems:'center', gap:12 }}>
                  <div style={{ width:12, height:12, borderRadius:'50%', background:dot, boxShadow:`0 0 8px ${dot}`, flexShrink:0 }} />
                  <div>
                    <div style={{ fontSize:11, fontWeight:700, color:'#fff', letterSpacing: 0.5 }}>{label}</div>
                    <div style={{ fontSize:10, color:'rgba(255,255,255,0.4)', marginTop: 2 }}>{desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <Card>
            <div style={{ fontSize:10, color:'rgba(255,255,255,0.4)', letterSpacing:1.5, textTransform:'uppercase', marginBottom:16, fontWeight:600 }}>Big Five Axes</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <Bar label="Warmth"        value={personality?.warmth        ?? 0} color="#ffd93d" />
              <Bar label="Energy"        value={personality?.energy        ?? 0} color="#fb923c" />
              <Bar label="Assertiveness" value={personality?.assertiveness ?? 0} color="#f43f5e" />
              <Bar label="Formality"     value={personality?.formality     ?? 0} color="#6bcbef" />
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECURITY COMMAND CENTER
// ═══════════════════════════════════════════════════════════════════════════════

const AGENT_META = {
  api_security: { label: 'API Guard',    icon: '🌐', desc: 'WebSocket & auth' },
  integrity:    { label: 'Integrity',    icon: '🧬', desc: 'File tamper watch' },
  network:      { label: 'Network',      icon: '📡', desc: 'Connection monitor' },
  memory:       { label: 'Memory',       icon: '💾', desc: 'Leak detection' },
  cve:          { label: 'CVE Scanner',  icon: '🔍', desc: 'Known vulnerabilities' },
  sandbox:      { label: 'Sandbox',      icon: '🧪', desc: 'Injection tests' },
  mobile:       { label: 'Mobile',       icon: '📱', desc: 'Permission monitor' },
  risk_engine:  { label: 'Risk Engine',  icon: '⚖️', desc: 'Score aggregator' },
};

const RISK_COLOR = {
  HIGH:   '#ef4444',
  MEDIUM: '#f97316',
  LOW:    '#10b981',
  SAFE:   '#22d3ee',
};

const SEV_BADGE_COLOR = {
  HIGH:   { bg: 'rgba(239,68,68,0.18)',   border: '#ef4444', text: '#ef4444'   },
  MEDIUM: { bg: 'rgba(249,115,22,0.18)',  border: '#f97316', text: '#f97316'   },
  LOW:    { bg: 'rgba(16,185,129,0.18)',  border: '#10b981', text: '#10b981'   },
};

// ── Build Tab ────────────────────────────────────────────────────────────────
const BUILD_TYPE_COLORS = { js: '#ffd93d', css: '#00f2ff', html: '#ff8fa3', other: '#a78bfa' };

function BuildTab() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  // Guard against setState after unmount (tabs unmount on switch) — matches
  // the mounted-flag convention used elsewhere in this file.
  const mountedRef = useRef(true);
  useEffect(() => () => { mountedRef.current = false; }, []);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const host = window.location.hostname || 'localhost';
      const res = await fetch(`http://${host}:8000/api/build/summary`);
      if (mountedRef.current) {
        if (res.ok) {
          const d = await res.json();
          setData(d && d.found ? d : null);
        } else {
          setData(null);
        }
      }
    } catch {
      if (mountedRef.current) {
        setData(null);
        setError(true);
      }
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const fmtBytes = (bytes) => {
    if (!Number.isFinite(bytes) || bytes < 0) return '—';
    if (bytes < 1024) return `${bytes} B`;
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let v = bytes;
    let u = 0;
    while (v >= 1024 && u < units.length - 1) { v /= 1024; u++; }
    return `${v >= 100 ? Math.round(v) : v.toFixed(1)} ${units[u]}`;
  };

  const refreshBtn = {
    background: 'rgba(0,242,255,0.08)', border: '1px solid rgba(0,242,255,0.3)',
    color: '#00f2ff', borderRadius: 6, padding: '6px 14px', cursor: 'pointer',
    fontSize: 11, fontWeight: 700, letterSpacing: 1, transition: 'all 0.2s',
  };

  if (loading) {
    return (
      <div style={{ color: 'rgba(255,255,255,0.3)', textAlign: 'center', padding: '80px 0', fontSize: 13 }}>
        ⟳ Loading build summary…
      </div>
    );
  }

  if (!data) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
        <SectionHeader title="Build Output" sub="Production bundle stats from `npm run dev -- --prod`" />
        <Card style={{ textAlign: 'center', padding: '60px 20px' }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>📦</div>
          <div style={{ fontSize: 15, color: '#fff', marginBottom: 6 }}>
            {error ? 'Backend unreachable' : 'No build summary yet'}
          </div>
          <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.4)', marginBottom: 18, maxWidth: 520, margin: '0 auto 18px' }}>
            {error
              ? 'Could not reach the brain at :8000 — check that the backend is running.'
              : 'Run `npm run dev -- --prod` once — the dist/ size, per-type breakdown and build time will appear here automatically.'}
          </div>
          <button
            onClick={load}
            style={refreshBtn}
            onMouseOver={e => { e.currentTarget.style.background = 'rgba(0,242,255,0.2)'; }}
            onMouseOut={e => { e.currentTarget.style.background = 'rgba(0,242,255,0.08)'; }}
          >⟳ Refresh</button>
        </Card>
      </div>
    );
  }

  const total = data.total || 0;
  const types = Object.entries(data.byType || {})
    .filter(([, t]) => t && t.count > 0)
    .sort((a, b) => b[1].size - a[1].size);
  const builtAt = data.built_at ? new Date(data.built_at).toLocaleString() : '—';

  // Muted 'outdated' hint when the summary is older than the configured
  // freshness window (BUILD_WARN_MAX_AGE_HOURS) — the same rule the
  // main-window banner uses to hide stale warnings.
  const stale = !isBuildSummaryFresh(data.built_at);
  const ageText = (() => {
    // Parse like the helper does — raw epoch-ms numbers are used directly, since
    // Date.parse would coerce them to a numeric string (NaN in V8).
    const built = typeof data.built_at === 'number' ? data.built_at : (data.built_at ? Date.parse(data.built_at) : NaN);
    const ms = Date.now() - built;
    if (!Number.isFinite(ms) || ms < 0) return null;
    const h = Math.floor(ms / 3600000);
    // h/d boundary is a display convention, intentionally NOT tied to the
    // freshness window (BUILD_WARN_MAX_AGE_HOURS): for a window < 24h,
    // Math.floor(h/24) would otherwise show '0d' for legitimately-stale data.
    return h < 24 ? `${h}h` : `${Math.floor(h / 24)}d`;
  })();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <SectionHeader title="Build Output" sub={data.dir || 'Production bundle from `npm run dev -- --prod`'} />
          {stale && (
            <span
              title={`Built ${builtAt} — older than ${BUILD_WARN_MAX_AGE_HOURS}h, data shown for reference`}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 5,
                padding: '2px 9px', borderRadius: 10, marginTop: 2,
                background: 'rgba(148,163,184,0.08)', border: '1px solid rgba(148,163,184,0.22)',
                color: 'rgba(255,255,255,0.45)', fontSize: 9.5, fontWeight: 700,
                letterSpacing: 1, textTransform: 'uppercase', whiteSpace: 'nowrap',
              }}
            >
              ⏳ Outdated{ageText ? ` · ${ageText} old` : ''}
            </span>
          )}
        </div>
        <button
          onClick={load}
          style={refreshBtn}
          onMouseOver={e => { e.currentTarget.style.background = 'rgba(0,242,255,0.2)'; }}
          onMouseOut={e => { e.currentTarget.style.background = 'rgba(0,242,255,0.08)'; }}
        >⟳ Refresh</button>
      </div>

      {/* KPI row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
        <KpiCard label="Bundle Size" value={fmtBytes(total)} color="#00f2ff" icon="📦" />
        <KpiCard label="Files" value={data.files ?? 0} color="#3b82f6" icon="📄" />
        <KpiCard label="Build Time" value={data.build_time_s != null ? `${data.build_time_s.toFixed(1)}s` : '—'} color="#ffd93d" icon="⏱️" />
        <KpiCard label="Built At" value={<span style={{ fontSize: 12 }}>{builtAt}</span>} color="#a78bfa" icon="🕒" />
      </div>

      {/* Chunk-size warnings */}
      {data.warnings && data.warnings.length > 0 && (
        <Card accentColor="#f59e0b" style={{ borderColor: 'rgba(245,158,11,0.35)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
            <span style={{ fontSize: 20 }}>⚠️</span>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: '#fbbf24', letterSpacing: 0.5 }}>
                {data.warnings.length} JS chunk{data.warnings.length === 1 ? '' : 's'} over the {data.chunk_warn_kb ?? 500} KB warn threshold
              </div>
              <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)' }}>
                Large chunks delay initial load — consider code-splitting. Threshold configurable via BUILD_CHUNK_WARN_KB.
              </div>
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {data.warnings.map((f, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, fontSize: 12, color: 'rgba(255,255,255,0.8)', fontFamily: "'JetBrains Mono', monospace", padding: '6px 10px', background: 'rgba(245,158,11,0.06)', borderRadius: 6 }}>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={f.rel}>{f.rel}</span>
                <span style={{ fontWeight: 700, color: '#fbbf24', flexShrink: 0 }}>{fmtBytes(f.size)}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Per-type breakdown */}
      <Card>
        <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 16 }}>Bundle by Type</div>
        {types.map(([key, t]) => {
          const pct = total > 0 ? (t.size / total) * 100 : 0;
          const color = BUILD_TYPE_COLORS[key] || '#a78bfa';
          return (
            <div key={key} style={{ marginBottom: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'rgba(255,255,255,0.6)', marginBottom: 4 }}>
                <span style={{ fontWeight: 700, color }}>{String(key).toUpperCase()}</span>
                <span style={{ fontFamily: 'monospace' }}>{fmtBytes(t.size)} · {t.count} file{t.count === 1 ? '' : 's'} · {pct.toFixed(1)}%</span>
              </div>
              <div style={{ height: 6, background: 'rgba(255,255,255,0.07)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3, boxShadow: `0 0 8px ${color}60`, transition: 'width 0.5s ease' }} />
              </div>
            </div>
          );
        })}
      </Card>

      {/* Largest files */}
      <Card>
        <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 12 }}>Largest Files</div>
        {(data.largest || []).length === 0 ? (
          <div style={{ color: 'rgba(255,255,255,0.2)', textAlign: 'center', padding: '30px 0', fontSize: 12 }}>No files recorded.</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {data.largest.map((f, i) => {
              const pct = total > 0 ? (f.size / total) * 100 : 0;
              const color = i === 0 ? '#ffd93d' : i === 1 ? '#00f2ff' : 'rgba(255,255,255,0.4)';
              return (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 12px', background: 'rgba(255,255,255,0.02)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.05)' }}>
                  <span style={{ width: 22, fontSize: 11, fontWeight: 800, color, fontFamily: 'monospace' }}>#{i + 1}</span>
                  <span style={{ flex: 1, fontSize: 12, color: 'rgba(255,255,255,0.8)', fontFamily: "'JetBrains Mono', monospace", overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={f.rel}>{f.rel}</span>
                  <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)', fontFamily: 'monospace', width: 60, textAlign: 'right' }}>{pct.toFixed(1)}%</span>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#fff', fontFamily: 'monospace', width: 70, textAlign: 'right' }}>{fmtBytes(f.size)}</span>
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}

function SecurityTab({ data }) {
  const issues   = data?.issues   || [];
  const risk     = data?.risk     || { risk_level: 'SAFE', risk_score: 0 };
  const actions  = data?.actions  || [];
  const timeline = data?.timeline || [];

  // Agent risk map: agent → highest severity found
  const agentRisk = {};
  for (const issue of issues) {
    const prev = agentRisk[issue.agent];
    const sev  = issue.severity;
    if (!prev || (sev === 'HIGH') || (sev === 'MEDIUM' && prev === 'LOW')) {
      agentRisk[issue.agent] = sev;
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <SectionHeader
        title="Security Command Center"
        sub="Real-time multi-agent vulnerability monitoring · 7 active security agents"
      />

      {/* ── TOP ROW: Risk Meter + Stats ──────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr', gap: 20 }}>
        <SecurityRiskMeter risk={risk} />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14 }}>
          <SecKpiCard
            icon="⚠️" label="Active Issues"
            value={issues.length}
            color={issues.length > 0 ? '#ef4444' : '#10b981'}
          />
          <SecKpiCard
            icon="🔧" label="Auto-Fixes"
            value={actions.length}
            color="#22d3ee"
          />
          <SecKpiCard
            icon="📜" label="Events Logged"
            value={timeline.length}
            color="#a78bfa"
          />
        </div>
      </div>

      {/* ── AGENT SWARM ──────────────────────────────────────────────── */}
      <SecuritySwarmPanel agentRisk={agentRisk} />

      {/* ── BOTTOM ROW: Threat Feed + Timeline ───────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
        <ThreatFeed issues={issues} />
        <AutoFixLog actions={actions} />
      </div>

      <AttackTimeline timeline={timeline} />

      {/* ── CVE SCANNER — Live SAST + SCA from server ─────────────── */}
      <div style={{
        background: 'rgba(10,14,30,0.7)',
        border: '1px solid rgba(167,139,250,0.15)',
        borderRadius: 16, padding: 20,
        backdropFilter: 'blur(14px)',
        boxShadow: '0 0 32px rgba(167,139,250,0.06)',
      }}>
        <CveScannerPanel />
      </div>

      {/* ── EMPTY STATE ──────────────────────────────────────────────── */}
      {!data && (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', gap: 14, padding: '60px 0',
          color: 'rgba(255,255,255,0.25)',
        }}>
          <span style={{ fontSize: 48 }}>🔐</span>
          <div style={{ fontSize: 14, letterSpacing: 1 }}>Waiting for first cognitive loop scan…</div>
          <div style={{ fontSize: 11, opacity: 0.6 }}>Security agents run automatically on every message</div>
        </div>
      )}
    </div>
  );
}

// ── Risk Meter ────────────────────────────────────────────────────────────────
function SecurityRiskMeter({ risk }) {
  const level = risk.risk_level || 'SAFE';
  const score = risk.risk_score || 0;
  const color = RISK_COLOR[level] || '#22d3ee';
  const maxScore = 20;  // rough cap for visual pct
  const pct = Math.min(100, (score / maxScore) * 100);

  const pulseStyle = level === 'HIGH' ? {
    animation: 'criticalPulse 1.5s infinite',
  } : {};

  return (
    <div style={{
      background: `radial-gradient(circle at center, ${color}14 0%, transparent 70%)`,
      border: `1px solid ${color}40`,
      borderRadius: 16, padding: 20,
      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10,
      ...pulseStyle,
    }}>
      <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.4)', letterSpacing: 2, textTransform: 'uppercase' }}>Risk Level</div>
      <div style={{ fontSize: 32, fontWeight: 800, color, fontFamily: 'monospace', letterSpacing: 2 }}>{level}</div>
      <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.5)', fontFamily: 'monospace' }}>score: {score}</div>
      {/* Bar */}
      <div style={{ width: '100%', height: 6, background: 'rgba(255,255,255,0.07)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{
          width: `${pct}%`, height: '100%',
          background: `linear-gradient(90deg, ${color}88, ${color})`,
          borderRadius: 3, transition: 'width 0.6s ease',
          boxShadow: pct > 0 ? `0 0 10px ${color}60` : 'none',
        }} />
      </div>
    </div>
  );
}

// ── Agent Swarm Nodes ─────────────────────────────────────────────────────────
function SecuritySwarmPanel({ agentRisk }) {
  const agents = Object.keys(AGENT_META);

  return (
    <Card style={{ padding: '20px 24px' }}>
      <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 16 }}>Security Agent Swarm</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14 }}>
        {agents.map(agent => {
          const meta  = AGENT_META[agent];
          const sev   = agentRisk[agent];
          const color = sev ? (RISK_COLOR[sev] || '#22d3ee') : '#22d3ee';
          const isHot = Boolean(sev && sev !== 'SAFE');

          return (
            <div key={agent} style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center',
              gap: 8, cursor: 'default',
            }}>
              {/* Glowing orb */}
              <div style={{
                width: 52, height: 52, borderRadius: '50%',
                background: `radial-gradient(circle at 35% 35%, ${color}55, ${color}18)`,
                border: `2px solid ${color}${isHot ? 'cc' : '44'}`,
                boxShadow: isHot ? `0 0 18px ${color}80, 0 0 6px ${color}40` : `0 0 6px ${color}25`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 20,
                animation: isHot && sev === 'HIGH' ? 'criticalPulse 1.8s infinite' : 'none',
                transition: 'all 0.4s ease',
              }}>
                {meta.icon}
              </div>
              {/* Label */}
              <div style={{ fontSize: 10, fontWeight: 700, color, letterSpacing: 0.5, textAlign: 'center' }}>
                {meta.label}
              </div>
              {/* Status badge */}
              <div style={{
                fontSize: 9, fontWeight: 700, letterSpacing: 0.8, textTransform: 'uppercase',
                padding: '2px 7px', borderRadius: 4,
                background: sev ? `${RISK_COLOR[sev]}22` : 'rgba(34,211,238,0.1)',
                color: sev ? RISK_COLOR[sev] : '#22d3ee',
                border: `1px solid ${sev ? RISK_COLOR[sev] : '#22d3ee'}44`,
              }}>
                {sev || 'SAFE'}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

// ── Threat Feed ───────────────────────────────────────────────────────────────
function ThreatFeed({ issues }) {
  const [ignored, setIgnored] = useState(new Set());
  
  const activeIssues = issues.filter(i => !ignored.has(i.issue));

  return (
    <Card>
      <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 14, display: 'flex', justifyContent: 'space-between' }}>
        <span>🚨 Threat Feed</span>
        <span>{activeIssues.length} Active</span>
      </div>
      {activeIssues.length === 0 ? (
        <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.25)', textAlign: 'center', padding: '24px 0' }}>✅ No active threats</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: 320, overflowY: 'auto' }}>
          {activeIssues.map((issue, i) => {
            const bc = SEV_BADGE_COLOR[issue.severity] || SEV_BADGE_COLOR.LOW;
            return (
              <div key={i} style={{
                background: `${bc.bg}`, border: `1px solid ${bc.border}30`,
                borderRadius: 10, padding: '12px 14px',
                borderLeft: `3px solid ${bc.border}`,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <span style={{
                    fontSize: 9, fontWeight: 800, letterSpacing: 1.2, textTransform: 'uppercase',
                    color: bc.text, background: `${bc.bg}`, border: `1px solid ${bc.border}55`,
                    padding: '2px 7px', borderRadius: 4,
                  }}>{issue.severity}</span>
                  <span style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', fontFamily: 'monospace' }}>agent: {issue.agent}</span>
                </div>
                <div style={{ fontSize: 12, color: '#fff', fontWeight: 600, marginBottom: 4 }}>{issue.issue}</div>
                <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)', marginBottom: 8 }}>💡 {issue.fix}</div>
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                  <button 
                    onClick={() => {
                      const text = `🚨 Threat Report: ${issue.severity}\nAgent: ${issue.agent}\nIssue: ${issue.issue}\nFix: ${issue.fix}`;
                      navigator.clipboard.writeText(text);
                    }}
                    style={{
                      padding: '4px 10px', borderRadius: 4, fontSize: 9, fontWeight: 700,
                      background: 'transparent', border: `1px solid ${bc.border}30`, color: bc.text, cursor: 'pointer'
                    }}
                  >
                    📋 COPY THREAT
                  </button>
                  <button 
                    onClick={() => setIgnored(prev => new Set([...prev, issue.issue]))}
                    style={{
                      padding: '4px 10px', borderRadius: 4, fontSize: 9, fontWeight: 700,
                      background: 'transparent', border: `1px solid ${bc.border}50`, color: bc.text, cursor: 'pointer'
                    }}
                  >
                    ✓ ACKNOWLEDGE
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

// ── Auto-Fix Log ──────────────────────────────────────────────────────────────
function AutoFixLog({ actions }) {
  return (
    <Card>
      <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 14 }}>🔧 Auto-Fix Log</div>
      {actions.length === 0 ? (
        <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.25)', textAlign: 'center', padding: '24px 0' }}>No remediation actions taken</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 320, overflowY: 'auto' }}>
          {actions.map((action, i) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '10px 12px', borderRadius: 8,
              background: 'rgba(34,211,238,0.06)',
              border: '1px solid rgba(34,211,238,0.15)',
            }}>
              <span style={{ fontSize: 16 }}>✅</span>
              <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.8)' }}>{action}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ── Attack Timeline ───────────────────────────────────────────────────────────
function AttackTimeline({ timeline }) {
  if (!timeline || timeline.length === 0) return null;

  const fmtTime = (ts) => {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  const typeColor = {
    THREAT_DETECTED:  '#ef4444',
    RISK_ASSESSMENT:  '#f97316',
    REMEDIATION:      '#22d3ee',
  };

  const typeIcon = {
    THREAT_DETECTED:  '🔴',
    RISK_ASSESSMENT:  '⚖️',
    REMEDIATION:      '🔧',
  };

  return (
    <Card>
      <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 14 }}>📜 Attack Timeline</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0, maxHeight: 260, overflowY: 'auto', position: 'relative' }}>
        {/* Connecting line */}
        <div style={{ position: 'absolute', left: 14, top: 0, bottom: 0, width: 2, background: 'rgba(255,255,255,0.06)', zIndex: 0 }} />
        {timeline.slice(0, 40).map((event, i) => {
          const color = typeColor[event.type] || '#94a3b8';
          const icon  = typeIcon[event.type]  || '📌';
          const label = event.type === 'THREAT_DETECTED'
            ? (event.issue?.issue || 'Threat')
            : event.type === 'RISK_ASSESSMENT'
            ? `Risk: ${event.risk_level} (score ${event.risk_score})`
            : (event.action || 'Action');

          return (
            <div key={i} style={{
              display: 'flex', alignItems: 'flex-start', gap: 12,
              padding: '8px 0', zIndex: 1, position: 'relative',
            }}>
              {/* Dot */}
              <div style={{
                width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
                background: `${color}22`, border: `1.5px solid ${color}66`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 12,
              }}>{icon}</div>
              {/* Content */}
              <div style={{ flex: 1, paddingTop: 4 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: '#fff' }}>{label}</div>
                <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.35)', marginTop: 2, fontFamily: 'monospace' }}>
                  {event.agent && <span style={{ color: color, marginRight: 8 }}>{event.agent}</span>}
                  {fmtTime(event.timestamp)}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

// ── Security KPI Card ─────────────────────────────────────────────────────────
function SecKpiCard({ icon, label, value, color }) {
  return (
    <div style={{
      background: 'rgba(30,41,59,0.4)',
      border: `1px solid ${color}28`,
      borderRadius: 12, padding: '16px 18px',
      display: 'flex', flexDirection: 'column', gap: 8,
    }}>
      <div style={{ fontSize: 20 }}>{icon}</div>
      <div style={{ fontSize: 26, fontWeight: 800, color, fontFamily: 'monospace' }}>{value}</div>
      <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)', letterSpacing: 1, textTransform: 'uppercase' }}>{label}</div>
    </div>
  );
}