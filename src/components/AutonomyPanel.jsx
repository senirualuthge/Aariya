import React from 'react';
import useStore from '../store';
import DraggablePanel from './DraggablePanel';

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
      className="ui-panel"
      style={{
        minWidth: '300px',
        maxHeight: '70vh',
        zIndex: 18,
        background: 'rgba(14, 10, 18, 0.72)',
        backdropFilter: 'blur(18px)',
        WebkitBackdropFilter: 'blur(18px)',
        border: '1px solid rgba(255, 143, 163, 0.22)',
        boxShadow: '0 12px 40px rgba(0,0,0,0.45), inset 0 0 24px rgba(255, 143, 163, 0.04)',
        borderRadius: '14px',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* ── Header (drag handle) ─────────────────────────────────────────── */}
      <div
        className="drag-handle"
        style={{
          cursor: 'grab',
          padding: '0.7rem 1rem',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 8,
          background: 'linear-gradient(90deg, rgba(255,143,163,0.14), rgba(0,242,255,0.05))',
          borderBottom: '1px solid rgba(255,143,163,0.18)',
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
      <div style={{ flex: 1, overflowY: 'auto', padding: '0.9rem 1rem' }} className="scrollbar-hide">

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
              style={{
                border: '1px solid rgba(0,242,255,0.3)',
                background: 'rgba(0,242,255,0.05)',
                borderRadius: 10,
                padding: '0.7rem 0.8rem',
                marginBottom: '1rem',
                animation: 'fadeIn 0.4s ease-out',
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
