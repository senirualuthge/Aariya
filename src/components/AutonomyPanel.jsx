import React, { useEffect, useRef, useState } from 'react';
import useStore from '../store';
import DraggablePanel from './DraggablePanel';

// BroadcastChannel bridge to the Analytics dashboard window (same channel the
// dashboard already listens on). Used to jump the Event Log to a matching line.
const BC = (() => {
  try { return new BroadcastChannel('aariya_control'); }
  catch { return null; }
})();

const triggerMeta = {
  distress:    { label: 'Concern',  color: '#ff6b6b', emoji: '🫂' },
  escalation:  { label: 'Energy',   color: '#ffb347', emoji: '⚡' },
  insight:     { label: 'Insight',  color: '#a8e6cf', emoji: '📚' },
  opportunity: { label: 'Plan',     color: '#00f2ff', emoji: '🗺️' },
  curiosity:   { label: 'Curious',  color: '#e8a9f0', emoji: '✨' },
  silence:     { label: 'Check-in', color: '#6bcbef', emoji: '💬' },
  check_in:    { label: 'Check-in', color: '#6bcbef', emoji: '💬' },
  startup_brief: { label: 'Awake',  color: '#ffd93d', emoji: '🌌' },
  plan_step:   { label: 'Plan step', color: '#00f2ff', emoji: '▶️' },
};

// Plan lifecycle status → chip look (the daemon's real plan status).
const planStatusMeta = {
  awaiting_approval: { label: 'AWAITING APPROVAL', color: '#00f2ff', pulse: true },
  proposed:          { label: 'PROPOSED',          color: '#6bcbef' },
  running:           { label: 'RUNNING',           color: '#7ee2a8', pulse: true },
  completed:         { label: 'COMPLETED',         color: '#7ee2a8' },
  failed:            { label: 'FAILED',            color: '#ff6b6b' },
  rejected:          { label: 'REJECTED',          color: '#ff6b6b' },
};

// Build a full per-minute series for the last hour (60 buckets, zero-filled so
// idle stretches show as 0 rather than gaps). Oldest → newest counts.
function buildRateSeries(rate, nowSec = Date.now() / 1000) {
  const curBucket = Math.floor(nowSec / 60);
  const startBucket = curBucket - 59;
  const byT = new Map();
  (rate || []).forEach((b) => {
    if (b && Number.isFinite(b.t)) byT.set(Math.floor(b.t / 60), b.c || 0);
  });
  const series = [];
  for (let b = startBucket; b <= curBucket; b++) series.push(byT.get(b) || 0);
  return series;
}

// Mini sparkline: real daemon events per minute over the last hour (the store's
// rate history — no synthetic data). Soft area fill + cyan line, with current
// events/min and peak in the corner.
function ActivitySparkline({ rate }) {
  const series = buildRateSeries(rate);
  const realMax = Math.max(...series);
  const peak = realMax > 0 ? realMax : 0;
  const last = series[series.length - 1] || 0;
  const W = 300, H = 26, P = 2;
  const step = (W - P * 2) / Math.max(1, series.length - 1);
  const pts = series.map((c, i) => {
    const x = P + i * step;
    const y = H - P - (c / Math.max(1, realMax)) * (H - P * 2);
    return [x.toFixed(1), y.toFixed(1)];
  });
  const line = pts.map((p) => p.join(',')).join(' ');
  const area = `M${P},${H - P} L${line} L${W - P},${H - P} Z`;
  return (
    <div style={{ marginTop: 8, borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 6 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 3 }}>
        <span style={{ fontSize: '0.5rem', letterSpacing: '1.5px', textTransform: 'uppercase', color: 'rgba(0,242,255,0.55)', fontWeight: 700 }}>
          ◢ Activity · last hour
        </span>
        <span style={{ fontSize: '0.5rem', color: 'rgba(255,255,255,0.35)', fontFamily: "'JetBrains Mono', monospace" }}>
          {last}/min{peak > 0 ? ` · peak ${peak}` : ''}
        </span>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        style={{ width: '100%', height: 26, display: 'block' }}
        role="img"
        aria-label={`Daemon activity over the last hour: ${last} events this minute, peak ${peak}`}
      >
        <path d={area} fill="rgba(0,242,255,0.07)" vectorEffect="non-scaling-stroke" />
        <path
          d={`M${line}`}
          fill="none"
          stroke="#00f2ff"
          strokeWidth={1.4}
          strokeLinejoin="round"
          strokeLinecap="round"
          opacity={0.85}
          vectorEffect="non-scaling-stroke"
        />
      </svg>
    </div>
  );
}

// Live strip: the daemon's most recent real action + plan status, so the
// Autonomy panel reflects what she's doing right now — not just the log.
// Every row is clickable: plan entries open the plan detail, other entries
// jump the Analytics dashboard's Event Log to the matching line.
function LiveStrip({ lastProactive, planStatus, activity, rate, fmtTime, onActivityClick, onJump }) {
  const recent = (activity || []).slice(0, 3);
  const hasAnything = lastProactive || planStatus || recent.length > 0;

  return (
    <div
      style={{
        border: '1px solid rgba(0,242,255,0.18)',
        background: 'linear-gradient(135deg, rgba(0,242,255,0.05), rgba(255,143,163,0.04))',
        borderRadius: 10,
        padding: '0.55rem 0.7rem',
        marginBottom: '0.9rem',
        position: 'relative',
      }}
    >
      {/* LIVE badge */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <span
          style={{
            fontSize: '0.5rem', fontWeight: 800, letterSpacing: '2px',
            color: '#00f2ff', textTransform: 'uppercase',
            display: 'flex', alignItems: 'center', gap: 5,
          }}
        >
          <span
            style={{
              width: 6, height: 6, borderRadius: '50%', background: '#00f2ff',
              boxShadow: '0 0 8px #00f2ff',
              animation: 'statusPulse 1.6s infinite',
            }}
          />
          Live
        </span>
        <span style={{ flex: 1, height: 1, background: 'rgba(0,242,255,0.12)' }} />
      </div>

      {!hasAnything && (
        <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: '0.72rem', fontStyle: 'italic' }}>
          Waiting for her first move…
        </div>
      )}

      {/* Latest proactive action — clickable: jumps to its DAEMON log line */}
      {lastProactive && (
        <div
          role="button"
          tabIndex={0}
          onClick={() => onJump && onJump({
            tag: 'DAEMON',
            text: `Proactive (${lastProactive.trigger}): ${String(lastProactive.content || '').slice(0, 60)}`,
            ts: lastProactive.timestamp,
          })}
          onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.click(); }}
          title="Jump to matching Event Log line"
          style={{
            display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: planStatus ? 8 : 0,
            cursor: 'pointer', borderRadius: 6, padding: '3px 4px', margin: '-3px -4px',
            transition: 'background 0.15s ease',
          }}
          onMouseOver={(e) => { e.currentTarget.style.background = 'rgba(0,242,255,0.07)'; }}
          onMouseOut={(e) => { e.currentTarget.style.background = 'transparent'; }}
        >
          <span style={{ fontSize: '0.95rem', lineHeight: '1rem' }}>
            {(triggerMeta[lastProactive.trigger] || {}).emoji || '💬'}
          </span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                fontSize: '0.58rem', letterSpacing: '1px', textTransform: 'uppercase',
                fontWeight: 700,
                color: (triggerMeta[lastProactive.trigger] || {}).color || '#ffd93d',
                marginBottom: 2,
              }}
            >
              {((triggerMeta[lastProactive.trigger] || {}).label || lastProactive.trigger).toUpperCase()}
            </div>
            <div
              style={{
                fontSize: '0.74rem', color: 'rgba(255,255,255,0.85)', lineHeight: 1.3,
                overflow: 'hidden', textOverflow: 'ellipsis',
                display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
              }}
            >
              {lastProactive.content}
            </div>
            <div style={{ fontSize: '0.52rem', color: 'rgba(255,255,255,0.3)', marginTop: 2 }}>
              {fmtTime(lastProactive.timestamp)}
            </div>
          </div>
          <span style={{ fontSize: '0.6rem', flexShrink: 0, opacity: 0.6 }}>↗</span>
        </div>
      )}

      {/* Plan status chip — clickable: opens the plan detail */}
      {planStatus && (() => {
        const meta = planStatusMeta[planStatus.status] || { label: planStatus.status, color: '#00f2ff' };
        return (
          <div
            role="button"
            tabIndex={0}
            onClick={() => onActivityClick && onActivityClick({
              kind: 'plan',
              plan_id: planStatus.plan_id,
              text: planStatus.goal,
            })}
            onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.click(); }}
            title="Open plan detail"
            style={{
              display: 'flex', alignItems: 'center', gap: 8, marginBottom: recent.length ? 8 : 0,
              cursor: 'pointer', borderRadius: 6, padding: '3px 4px', margin: '-3px -4px',
              transition: 'background 0.15s ease',
            }}
            onMouseOver={(e) => { e.currentTarget.style.background = 'rgba(0,242,255,0.07)'; }}
            onMouseOut={(e) => { e.currentTarget.style.background = 'transparent'; }}
          >
            <span
              style={{
                width: 8, height: 8, borderRadius: '50%', background: meta.color,
                boxShadow: meta.pulse ? `0 0 8px ${meta.color}` : 'none',
                animation: meta.pulse ? 'statusPulse 1.6s infinite' : 'none',
                flexShrink: 0,
              }}
            />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  fontSize: '0.55rem', letterSpacing: '1px', textTransform: 'uppercase',
                  fontWeight: 800, color: meta.color,
                }}
              >
                {meta.label}
              </div>
              <div style={{ fontSize: '0.68rem', color: 'rgba(255,255,255,0.65)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {planStatus.goal || planStatus.plan_id}
              </div>
            </div>
          </div>
        );
      })()}

      {/* Recent activity mini-feed (compact) — every row is clickable */}
      {recent.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginTop: 6, borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 6 }}>
          {recent.map((a, i) => {
            const isPlan = a.kind === 'plan' && a.plan_id;
            return (
              <button
                key={i}
                onClick={() => onActivityClick && onActivityClick(a)}
                title={isPlan ? 'Open plan detail' : 'Jump to matching Event Log line'}
                style={{
                  display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.62rem',
                  color: 'rgba(255,255,255,0.5)', minWidth: 0, cursor: 'pointer',
                  background: 'transparent', border: 'none', padding: '3px 4px',
                  borderRadius: 6, textAlign: 'left', fontFamily: 'inherit', width: '100%',
                  transition: 'background 0.15s ease, color 0.15s ease',
                }}
                onMouseOver={(e) => {
                  e.currentTarget.style.background = 'rgba(0,242,255,0.08)';
                  e.currentTarget.style.color = 'rgba(255,255,255,0.85)';
                }}
                onMouseOut={(e) => {
                  e.currentTarget.style.background = 'transparent';
                  e.currentTarget.style.color = 'rgba(255,255,255,0.5)';
                }}
              >
                <span style={{ width: 4, height: 4, borderRadius: '50%', background: '#00f2ff', flexShrink: 0 }} />
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {a.text}
                </span>
                <span style={{ fontSize: '0.5rem', color: 'rgba(255,255,255,0.25)', whiteSpace: 'nowrap', flexShrink: 0 }}>
                  {fmtTime(a.timestamp)}
                </span>
                <span style={{ fontSize: '0.55rem', flexShrink: 0, opacity: 0.7 }}>{isPlan ? '🗺' : '↗'}</span>
              </button>
            );
          })}
        </div>
      )}

      {/* Activity rate sparkline (real events per minute, last hour) */}
      {hasAnything && <ActivitySparkline rate={rate} />}
    </div>
  );
}

function StatusDot({ ok }) {
  return (
    <span
      style={{
        display: 'inline-block',
        width: 7,
        height: 7,
        borderRadius: '50%',
        background: ok ? '#7ee2a8' : '#ff6b6b',
        boxShadow: ok ? '0 0 6px #7ee2a8' : '0 0 6px #ff6b6b',
        marginRight: 6,
        flexShrink: 0,
      }}
    />
  );
}

function SectionTitle({ children, emoji, color = '#ff8fa3' }) {
  return (
    <div
      style={{
        fontSize: '0.62rem',
        fontWeight: 700,
        letterSpacing: '2.5px',
        textTransform: 'uppercase',
        color,
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        marginBottom: 8,
      }}
    >
      <span>{emoji}</span> {children}
    </div>
  );
}

export default function AutonomyPanel() {
  const autonomy = useStore((s) => s.autonomy);
  const toggleAutonomy = useStore((s) => s.toggleAutonomy);
  const approvePlan = useStore((s) => s.approvePlan);
  const rejectPlan = useStore((s) => s.rejectPlan);

  const goal = autonomy.activeGoal;
  const pendingPlan = autonomy.pendingPlan || null;
  const initiatives = autonomy.initiatives || [];
  const insights = autonomy.insights || [];
  const actions = autonomy.actions || [];
  const gaps = autonomy.gaps || [];

  // Click-to-open plan detail + flash for the pending approval card.
  const [detailPlan, setDetailPlan] = useState(null);
  const [flashPending, setFlashPending] = useState(false);
  const bodyRef = useRef(null);
  const flashTimerRef = useRef(null);

  // Keep an open plan-detail card honest: when the daemon's planStatus moves
  // (approve/reject/running/completed/failed), reflect it on the card so it
  // never sits on a stale 'awaiting_approval' with dead buttons.
  useEffect(() => {
    if (!detailPlan?.plan_id) return;
    const cur = autonomy.planStatus;
    if (cur?.plan_id && String(cur.plan_id) === String(detailPlan.plan_id) && cur.status && cur.status !== detailPlan.status) {
      setDetailPlan((d) => ({ ...d, status: cur.status }));
    }
  }, [autonomy.planStatus, detailPlan]);

  // Jump the Analytics dashboard's Event Log to a matching line: stash the
  // target so a freshly-opened dashboard consumes it on mount, broadcast to
  // an already-open dashboard, and open the dashboard window when needed.
  const jumpToLog = (logMatch) => {
    if (!logMatch || !logMatch.tag) return;
    try { sessionStorage.setItem('aariya_log_jump', JSON.stringify(logMatch)); }
    catch { /* storage blocked — broadcast alone still works */ }
    BC?.postMessage({ type: 'LOG_JUMP', ...logMatch });
    let dashOpen = false;
    try { dashOpen = sessionStorage.getItem('aariya_dashboard_open') === '1'; }
    catch { /* ignore */ }
    if (!dashOpen) {
      const host = window.location.hostname || 'localhost';
      const port = window.location.port || '5173';
      window.open(`http://${host}:${port}/?route=analytics`, '_blank', 'width=1200,height=800');
    }
  };

  // Plan entries: open the plan detail. The pending approval card is the
  // current plan's detail — scroll to it and flash. Other plans open an
  // inline detail card (from the last inner-world plans snapshot).
  const openPlanDetail = (planId, fallbackText) => {
    if (!planId) return;
    if (pendingPlan && String(pendingPlan.plan_id) === String(planId)) {
      setFlashPending(true);
      clearTimeout(flashTimerRef.current);
      flashTimerRef.current = setTimeout(() => setFlashPending(false), 1600);
      const card = bodyRef.current?.querySelector('#aariya_plan_awaiting');
      if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }
    const plan = (autonomy.plans || [])
      .find((p) => String(p.id ?? p.plan_id) === String(planId)) || null;
    setDetailPlan({
      plan_id: plan?.id ?? plan?.plan_id ?? planId,
      goal: plan?.goal_description || plan?.description || plan?.goal
        || autonomy.planStatus?.goal || fallbackText || planId,
      status: plan?.status || autonomy.planStatus?.status || null,
      risk_level: plan?.risk_level || autonomy.planStatus?.risk_level || 'low',
      steps: plan?.steps || [],
    });
    requestAnimationFrame(() => {
      const card = bodyRef.current?.querySelector('#aariya_plan_detail');
      if (card) card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
  };

  const handleActivityClick = (entry) => {
    if (!entry) return;
    if (entry.kind === 'plan' && entry.plan_id) {
      openPlanDetail(entry.plan_id, entry.text);
    } else if (entry.logMatch) {
      jumpToLog({ ...entry.logMatch, ts: entry.timestamp });
    }
  };

  const fmtTime = (ts) => {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  return (
    <DraggablePanel
      id="aariya_autonomy"
      defaultPosition={{ x: window.innerWidth - 430, y: window.innerHeight - 560 }}
      defaultSize={{ width: '340px', height: '440px' }}
      className="ui-panel chat-panel"
    >
      {/* ── Header (drag handle) ─────────────────────────────────────────── */}
      <div
        className="drag-handle panel-title-bar"
        style={{
          display: 'flex',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: '1.05rem' }}>🧠</span>
          <span
            style={{
              fontWeight: 800,
              letterSpacing: '1.5px',
              fontSize: '0.78rem',
              color: '#ffb3c1',
              textTransform: 'uppercase',
            }}
          >
            Aariya's Mind
          </span>
          <span
            style={{
              fontSize: '0.55rem',
              padding: '2px 7px',
              borderRadius: 20,
              letterSpacing: '1px',
              background: autonomy.enabled ? 'rgba(126,226,168,0.15)' : 'rgba(255,107,107,0.12)',
              color: autonomy.enabled ? '#7ee2a8' : '#ff6b6b',
              border: `1px solid ${autonomy.enabled ? 'rgba(126,226,168,0.35)' : 'rgba(255,107,107,0.35)'}`,
            }}
          >
            {autonomy.enabled ? '● AWAKE' : '○ ASLEEP'}
          </span>
        </div>

        {/* Toggle */}
        <button
          onClick={toggleAutonomy}
          title={autonomy.enabled ? 'Pause autonomy' : 'Resume autonomy'}
          style={{
            background: 'transparent',
            border: 'none',
            cursor: 'pointer',
            padding: 2,
            opacity: 0.85,
            transition: 'opacity 0.2s, transform 0.2s',
          }}
          onMouseOver={(e) => { e.currentTarget.style.opacity = 1; e.currentTarget.style.transform = 'scale(1.1)'; }}
          onMouseOut={(e) => { e.currentTarget.style.opacity = 0.85; e.currentTarget.style.transform = 'scale(1)'; }}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={autonomy.enabled ? '#7ee2a8' : '#ff6b6b'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="1" y="4" width="22" height="16" rx="8" />
            <circle cx={autonomy.enabled ? 17 : 7} cy="12" r="4" fill={autonomy.enabled ? '#7ee2a8' : '#ff6b6b'} />
          </svg>
        </button>
      </div>

      {/* ── Body ─────────────────────────────────────────────────────────── */}
      <div ref={bodyRef} style={{ flex: 1, overflowY: 'auto', padding: '0.9rem 1rem' }} className="scrollbar-hide">

        {/* ── Live strip: latest daemon action + plan status ────────────── */}
        <LiveStrip
          lastProactive={autonomy.lastProactive}
          planStatus={autonomy.planStatus}
          activity={autonomy.activity || []}
          rate={autonomy.rate || []}
          fmtTime={fmtTime}
          onActivityClick={handleActivityClick}
          onJump={jumpToLog}
        />

        {/* ── Plan detail (opened from a click on a plan strip entry) ───── */}
        {detailPlan && (
          <div
            id="aariya_plan_detail"
            style={{
              border: '1px solid rgba(0,242,255,0.25)',
              background: 'rgba(0,242,255,0.04)',
              borderRadius: 10,
              padding: '0.7rem 0.8rem',
              marginBottom: '1rem',
              animation: 'fadeIn 0.3s ease-out',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <span style={{ fontSize: '0.55rem', letterSpacing: '1.5px', textTransform: 'uppercase', color: '#00f2ff', fontWeight: 800 }}>
                🗺️ Plan Detail
              </span>
              <button
                onClick={() => setDetailPlan(null)}
                title="Close"
                style={{ background: 'transparent', border: 'none', color: 'rgba(255,255,255,0.4)', cursor: 'pointer', fontSize: '0.72rem' }}
              >✕</button>
            </div>
            <div style={{ fontSize: '0.8rem', color: '#e0fbff', marginBottom: 4 }}>{detailPlan.goal}</div>
            <div style={{ fontSize: '0.6rem', color: 'rgba(0,242,255,0.7)', marginBottom: 8, letterSpacing: '1px', textTransform: 'uppercase' }}>
              {(planStatusMeta[detailPlan.status] || { label: detailPlan.status || 'unknown' }).label}
              {' · Risk: '}{detailPlan.risk_level || 'low'}{' · '}{(detailPlan.steps || []).length} steps
            </div>
            {(detailPlan.steps || []).slice(0, 6).map((s, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.72rem', color: 'rgba(224,251,255,0.85)' }}>
                <StatusDot ok={detailPlan.status !== 'failed' && detailPlan.status !== 'rejected'} />
                <span style={{ color: '#00f2ff', fontFamily: 'monospace', fontSize: '0.62rem' }}>{s.type}</span>
                <span style={{ color: 'rgba(255,255,255,0.55)' }}>— {s.description || s.type}</span>
              </div>
            ))}
            {detailPlan.status === 'awaiting_approval' && (
              <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                <button onClick={() => approvePlan(detailPlan.plan_id)} style={approveBtn(true)}>✓ Approve</button>
                <button onClick={() => rejectPlan(detailPlan.plan_id)} style={approveBtn(false)}>✕ Decline</button>
              </div>
            )}
          </div>
        )}

        {/* Active Goal */}
        <SectionTitle emoji="🎯">Active Goal</SectionTitle>
        {goal ? (
          <div
            style={{
              border: '1px solid rgba(255,143,163,0.25)',
              background: 'linear-gradient(135deg, rgba(255,143,163,0.10), rgba(0,242,255,0.04))',
              borderRadius: 10,
              padding: '0.6rem 0.8rem',
              marginBottom: '1rem',
            }}
          >
            <div style={{ fontSize: '0.8rem', color: '#ffe0e6', lineHeight: 1.35 }}>
              {goal.description}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
              <span style={{ fontSize: '0.55rem', letterSpacing: '1.5px', textTransform: 'uppercase', color: '#ff8fa3' }}>
                {goal.goal_type}
              </span>
              <span style={{ fontSize: '0.55rem', color: 'rgba(255,255,255,0.4)' }}>
                priority {(goal.priority || 0).toFixed(2)}
              </span>
              <div style={{ flex: 1, height: 3, background: 'rgba(255,255,255,0.08)', borderRadius: 2, marginLeft: 4 }}>
                <div
                  style={{
                    width: `${Math.round((goal.progress || 0) * 100)}%`,
                    height: '100%',
                    background: 'linear-gradient(90deg, #ff8fa3, #ffb3c1)',
                    borderRadius: 2,
                    transition: 'width 0.6s ease',
                  }}
                />
              </div>
            </div>
          </div>
        ) : (
          <div style={{ color: 'rgba(255,255,255,0.35)', fontSize: '0.75rem', fontStyle: 'italic', marginBottom: '1rem' }}>
            No active goal — Aariya is listening for signals…
          </div>
        )}

        {/* Pending plan — needs approval */}
        {pendingPlan && (
          <>
            <SectionTitle emoji="🗺️" color="#00f2ff">Plan Awaiting You</SectionTitle>
            <div
              id="aariya_plan_awaiting"
              style={{
                border: '1px solid rgba(0,242,255,0.3)',
                background: 'rgba(0,242,255,0.05)',
                borderRadius: 10,
                padding: '0.7rem 0.8rem',
                marginBottom: '1rem',
                animation: 'fadeIn 0.4s ease-out',
                boxShadow: flashPending ? '0 0 0 2px rgba(0,242,255,0.85), 0 0 26px rgba(0,242,255,0.35)' : 'none',
                transition: 'box-shadow 0.3s ease',
              }}
            >
              <div style={{ fontSize: '0.8rem', color: '#e0fbff', marginBottom: 4 }}>
                {pendingPlan.goal}
              </div>
              <div style={{ fontSize: '0.6rem', color: 'rgba(0,242,255,0.7)', marginBottom: 8, letterSpacing: '1px', textTransform: 'uppercase' }}>
                Risk: {pendingPlan.risk_level || 'low'} · {pendingPlan.steps?.length || 0} steps
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 10 }}>
                {(pendingPlan.steps || []).map((s, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.72rem', color: 'rgba(224,251,255,0.85)' }}>
                    <StatusDot ok />
                    <span style={{ color: '#00f2ff', fontFamily: 'monospace', fontSize: '0.62rem' }}>{s.type}</span>
                    <span style={{ color: 'rgba(255,255,255,0.55)' }}>— {s.description}</span>
                  </div>
                ))}
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={() => approvePlan(pendingPlan.plan_id)}
                  style={approveBtn(true)}
                  onMouseOver={(e) => { e.currentTarget.style.transform = 'scale(1.03)'; e.currentTarget.style.boxShadow = '0 4px 14px rgba(126,226,168,0.4)'; }}
                  onMouseOut={(e) => { e.currentTarget.style.transform = 'scale(1)'; e.currentTarget.style.boxShadow = 'none'; }}
                  onMouseDown={(e) => (e.currentTarget.style.transform = 'scale(0.97)')}
                  onMouseUp={(e) => (e.currentTarget.style.transform = 'scale(1.03)')}
                >
                  ✓ Approve
                </button>
                <button
                  onClick={() => rejectPlan(pendingPlan.plan_id)}
                  style={approveBtn(false)}
                  onMouseOver={(e) => { e.currentTarget.style.transform = 'scale(1.03)'; e.currentTarget.style.boxShadow = '0 4px 14px rgba(255,107,107,0.4)'; }}
                  onMouseOut={(e) => { e.currentTarget.style.transform = 'scale(1)'; e.currentTarget.style.boxShadow = 'none'; }}
                >
                  ✕ Decline
                </button>
              </div>
            </div>
          </>
        )}

        {/* Initiatives (recent proactive moments) */}
        <SectionTitle emoji="💫">Recent Initiatives</SectionTitle>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: '1rem' }}>
          {initiatives.length === 0 && (
            <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: '0.72rem', fontStyle: 'italic' }}>
              Nothing yet — she'll reach out when it matters.
            </div>
          )}
          {initiatives.slice(0, 5).map((init) => {
            const meta = triggerMeta[init.trigger_type] || { label: init.trigger_type, color: '#b8b8b8', emoji: '·' };
            return (
              <div
                key={init.id}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 8,
                  fontSize: '0.72rem',
                  color: 'rgba(255,255,255,0.75)',
                  borderLeft: `2px solid ${meta.color}`,
                  paddingLeft: 8,
                  background: 'rgba(255,255,255,0.03)',
                  borderRadius: 4,
                  padding: '5px 8px',
                }}
              >
                <span>{meta.emoji}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                    <span style={{ fontSize: '0.58rem', letterSpacing: '1px', textTransform: 'uppercase', color: meta.color, fontWeight: 700 }}>
                      {meta.label}
                    </span>
                    <span style={{ fontSize: '0.55rem', color: 'rgba(255,255,255,0.3)', whiteSpace: 'nowrap' }}>
                      {fmtTime(init.ts)}
                    </span>
                  </div>
                  <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {init.message || init.hint}
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Insights learned */}
        {(insights.length > 0) && (
          <>
            <SectionTitle emoji="📚" color="#a8e6cf">Learned While Away</SectionTitle>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: '1rem' }}>
              {insights.slice(0, 4).map((ins) => (
                <div
                  key={ins.id}
                  style={{
                    fontSize: '0.72rem',
                    color: 'rgba(232,255,240,0.8)',
                    background: 'rgba(168,230,207,0.06)',
                    borderRadius: 6,
                    padding: '6px 9px',
                    border: '1px solid rgba(168,230,207,0.15)',
                  }}
                >
                  <div style={{ fontWeight: 700, color: '#a8e6cf', fontSize: '0.72rem', marginBottom: 2 }}>
                    {ins.topic}
                  </div>
                  <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'rgba(255,255,255,0.55)' }}>
                    {ins.content}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {/* Research queue */}
        {(gaps.length > 0) && (
          <>
            <SectionTitle emoji="🔍" color="#ffd93d">Research Queue</SectionTitle>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: '1rem' }}>
              {gaps.slice(0, 4).map((gap) => (
                <div key={gap.id} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.7rem', color: 'rgba(255,255,255,0.65)' }}>
                  <StatusDot ok={gap.status !== 'failed'} />
                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{gap.topic}</span>
                  <span style={{ fontSize: '0.55rem', color: 'rgba(255,217,61,0.7)', textTransform: 'uppercase' }}>{gap.status}</span>
                </div>
              ))}
            </div>
          </>
        )}

        {/* Audit trail */}
        <SectionTitle emoji="🧾" color="#e8a9f0">Action Audit</SectionTitle>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, paddingBottom: 4 }}>
          {actions.length === 0 && (
            <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: '0.72rem', fontStyle: 'italic' }}>
              No autonomous actions executed yet.
            </div>
          )}
          {actions.slice(0, 8).map((act) => (
            <div key={act.id} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.7rem', color: 'rgba(255,255,255,0.6)' }}>
              <StatusDot ok={act.status === 'completed'} />
              <span style={{ fontFamily: 'monospace', fontSize: '0.62rem', color: '#e8a9f0' }}>{act.action_type}</span>
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {act.outcome || act.status}
              </span>
              <span style={{ fontSize: '0.55rem', color: 'rgba(255,255,255,0.3)' }}>{fmtTime(act.ts)}</span>
            </div>
          ))}
        </div>
      </div>
    </DraggablePanel>
  );
}

const approveBtn = (isApprove) => ({
  flex: 1,
  cursor: 'pointer',
  border: `1px solid ${isApprove ? 'rgba(126,226,168,0.4)' : 'rgba(255,107,107,0.4)'}`,
  background: isApprove ? 'rgba(126,226,168,0.12)' : 'rgba(255,107,107,0.10)',
  color: isApprove ? '#7ee2a8' : '#ff6b6b',
  borderRadius: 8,
  padding: '0.45rem 0',
  fontSize: '0.72rem',
  fontWeight: 700,
  letterSpacing: '1px',
  transition: 'all 0.2s cubic-bezier(0.175, 0.885, 0.32, 1.275)',
});
