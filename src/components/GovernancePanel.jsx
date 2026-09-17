import React, { useEffect, useState, useCallback } from 'react';
import DraggablePanel from './DraggablePanel';
import useStore from '../store';
import { apiBase } from '../utils/apiHost';

// ── API helper ────────────────────────────────────────────────────────────────
const API = `${apiBase()}/api/compliance`;

async function api(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) throw new Error(`compliance ${path} → ${res.status}`);
  return res.json();
}

const CONSENT_META = [
  { key: 'emotion_tracking', label: 'Emotion tracking', desc: 'Sense and reflect your emotional state', icon: '🎭' },
  { key: 'personality_drift', label: 'Personality drift', desc: 'Slow trait evolution from our relationship', icon: '🌱' },
  { key: 'memory_storage', label: 'Memory storage', desc: 'Persist memories and conversations', icon: '🧠' },
];

const MODE_META = {
  CALM: { color: '#6bcbef', label: 'Calm' },
  STEALTH: { color: '#a78bfa', label: 'Stealth' },
  COMBAT: { color: '#ff6b6b', label: 'Combat' },
};

const fmtPct = (v) => `${Math.round((v ?? 0) * 100)}%`;
const fmtDays = (d) => (d >= 1 ? `${d.toFixed(1)}d` : `${Math.round((d ?? 0) * 24)}h`);

function HealthGauge({ label, value, color, hint, icon }) {
  const pct = Math.round((value ?? 0) * 100);
  return (
    <div style={{ marginBottom: '0.7rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', marginBottom: 3 }}>
        <span style={{ color: 'rgba(255,255,255,0.75)' }}>{icon} {label}</span>
        <span style={{ color, fontWeight: 700 }}>{pct}%</span>
      </div>
      <div style={{ height: 6, background: 'rgba(255,255,255,0.08)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{
          width: `${pct}%`, height: '100%', borderRadius: 3, transition: 'width 0.6s ease',
          background: `linear-gradient(90deg, ${color}55, ${color})`,
          boxShadow: `0 0 8px ${color}66`,
        }} />
      </div>
      {hint && <div style={{ fontSize: '0.62rem', color: 'rgba(255,255,255,0.35)', marginTop: 2 }}>{hint}</div>}
    </div>
  );
}

function Toggle({ checked, onChange, disabled }) {
  return (
    <button
      onClick={() => onChange(!checked)}
      disabled={disabled}
      style={{
        width: 38, height: 20, borderRadius: 10, border: 'none', cursor: disabled ? 'not-allowed' : 'pointer',
        background: checked ? 'linear-gradient(90deg,#00f2ff,#6bcbef)' : 'rgba(255,255,255,0.15)',
        position: 'relative', transition: 'background 0.25s', opacity: disabled ? 0.5 : 1, flexShrink: 0,
      }}
      aria-pressed={checked}
    >
      <span style={{
        position: 'absolute', top: 2, left: checked ? 20 : 2, width: 16, height: 16, borderRadius: 8,
        background: '#fff', transition: 'left 0.25s', boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
      }} />
    </button>
  );
}

function Section({ title, icon, children, accent = '#00f2ff' }) {
  return (
    <div style={{ marginBottom: '0.9rem' }}>
      <div style={{
        fontSize: '0.62rem', letterSpacing: '2px', textTransform: 'uppercase', color: accent,
        fontWeight: 700, marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: 6,
      }}>
        <span>{icon}</span> {title}
      </div>
      {children}
    </div>
  );
}

export default function GovernancePanel() {
  const synoptic = useStore((s) => s.synoptic);
  const [consent, setConsent] = useState(null);      // {consents, age_band, frozen}
  const [health, setHealth] = useState(null);        // {latest, trend, history}
  const [busy, setBusy] = useState({});
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    try {
      const [c, h] = await Promise.all([
        api('/consent-status?user_id=user_default'),
        api('/health?user_id=user_default').catch(() => null),
      ]);
      setConsent(c);
      if (h) setHealth(h);
      setError('');
    } catch (e) {
      setError('Server unreachable — is the backend running?');
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 15000);
    return () => clearInterval(t);
  }, [refresh]);

  const run = async (label, fn) => {
    setBusy((b) => ({ ...b, [label]: true }));
    setNotice('');
    try {
      await fn();
      await refresh();
      setNotice(label);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy((b) => ({ ...b, [label]: false }));
    }
  };

  // Live state from the brain's synoptic frame (real measured values).
  const mode = synoptic?.behavior_mode?.mode;
  const modeMeta = MODE_META[mode] || MODE_META.CALM;
  const reason = synoptic?.emotion_reason;
  const liveHealth = synoptic?.companion_health || health?.latest;
  const govFlags = synoptic?.governance || {};
  const traitEngine = synoptic?.trait_engine;
  const transparency = synoptic?.transparency || liveHealth?.transparency || health?.transparency;

  const latest = liveHealth || {};
  const reviewer = latest.reviewer || {};
  const trend = latest.trend || {};

  // AI Girl 2 §map_state_to_ui: subtle hue shift toward her empathy level.
  const hueShift = ((traitEngine?.ui?.color_tone ?? 0.5) - 0.5) * 40; // ±20deg

  const exportPersonality = async () => {
    try {
      const data = await api('/personality/export?user_id=user_default');
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `aariya-personality-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      setNotice('export');
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  return (
    <DraggablePanel
      id="aariya_governance"
      defaultPosition={{ x: window.innerWidth - 340, y: 132 }}
      defaultSize={{ width: '300px', height: '560px' }}
      className="ui-panel chat-panel"
      style={{ filter: `hue-rotate(${hueShift.toFixed(1)}deg)`, transition: 'filter 0.8s ease' }}
    >
      <div className="drag-handle panel-title-bar" style={{ gap: 8, padding: '0.7rem 0.9rem', color: '#e8f6ff' }}>
        <span style={{ fontSize: '0.95rem' }}>🛡️</span>
        <div>
          <div style={{ fontSize: '0.8rem', fontWeight: 700, letterSpacing: '1px', color: '#e8f6ff' }}>Companion Governance</div>
          <div style={{ fontSize: '0.6rem', color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '1px' }}>Consent · Age · Health</div>
        </div>
        {mode && (
          <span style={{ marginLeft: 'auto', padding: '3px 8px', borderRadius: 10, fontSize: '0.62rem', fontWeight: 800, letterSpacing: '1px', color: modeMeta.color, border: `1px solid ${modeMeta.color}66`, background: `${modeMeta.color}18` }}>
            ● {modeMeta.label}
          </span>
        )}
      </div>

      <div style={{ padding: '0.9rem', overflowY: 'auto', maxHeight: 'calc(100% - 96px)' }}>
        {error && (
          <div style={{ background: 'rgba(255,107,107,0.12)', border: '1px solid rgba(255,107,107,0.3)', color: '#ffb3b3', padding: '0.5rem', borderRadius: 8, fontSize: '0.72rem', marginBottom: '0.8rem' }}>{error}</div>
        )}
        {notice && !error && (
          <div style={{ background: 'rgba(0,242,255,0.08)', border: '1px solid rgba(0,242,255,0.25)', color: '#9df2ff', padding: '0.4rem 0.6rem', borderRadius: 8, fontSize: '0.68rem', marginBottom: '0.8rem' }}>
            ✓ {notice.replace(/_/g, ' ')} applied
          </div>
        )}

        {/* ── Consent matrix ─────────────────────────────────────────────── */}
        <Section title="Consent matrix" icon="📜">
          {(consent?.consents || govFlags?.consents || {}) && CONSENT_META.map((c) => {
            const checked = consent?.consents?.[c.key] ?? govFlags?.consents?.[c.key] ?? true;
            return (
              <div key={c.key} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '0.4rem 0', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                <span style={{ fontSize: '0.95rem' }}>{c.icon}</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: '0.74rem', color: '#e8f6ff' }}>{c.label}</div>
                  <div style={{ fontSize: '0.62rem', color: 'rgba(255,255,255,0.4)' }}>{c.desc}</div>
                </div>
                <Toggle
                  checked={checked}
                  disabled={busy[c.key]}
                  onChange={(v) => run(c.key, () => api('/consent', {
                    method: 'POST',
                    body: JSON.stringify({ user_id: 'user_default', consent: { [c.key]: v } }),
                  }))}
                />
              </div>
            );
          })}
        </Section>

        {/* ── Age policy ────────────────────────────────────────────────── */}
        <Section title="Age policy" icon="🎂" accent="#ffb3c1">
          <div style={{
            padding: '0.5rem', borderRadius: 8, border: '1px solid rgba(255,179,193,0.25)',
            background: 'rgba(255,179,193,0.1)', color: '#ffd7de', fontSize: '0.72rem',
            fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8,
          }}>
            🔒 18+ (locked)
          </div>
          <div style={{ fontSize: '0.62rem', color: 'rgba(255,255,255,0.5)', marginTop: 6 }}>
            The companion persona is always adult — age policy cannot be changed.
          </div>
        </Section>

        {/* ── Personality controls ──────────────────────────────────────── */}
        <Section title="Personality" icon="🌱" accent="#a8e6cf">
          <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
            <button
              disabled={busy['freeze']}
              onClick={() => {
                const frozen = consent?.frozen ?? govFlags?.frozen ?? false;
                run('freeze', () => api(frozen ? '/personality/unfreeze' : '/personality/freeze', {
                  method: 'POST',
                  body: JSON.stringify({ user_id: 'user_default' }),
                }));
              }}
              style={btnStyle(busy['freeze'])}
            >
              {(consent?.frozen ?? govFlags?.frozen) ? '❄️ Unfreeze' : '❄️ Freeze drift'}
            </button>
            <button disabled={busy['reset']} onClick={() => {
              if (window.confirm('Reset personality to defaults? Evolution history will be dropped.')) {
                run('reset', () => api('/personality/reset', { method: 'POST', body: JSON.stringify({ user_id: 'user_default' }) }));
              }
            }} style={btnStyle(busy['reset'])}>↺ Reset</button>
            <button disabled={busy['export']} onClick={exportPersonality} style={btnStyle(busy['export'])}>⬇ Export</button>
          </div>
          {(consent?.frozen ?? govFlags?.frozen) && (
            <div style={{ fontSize: '0.62rem', color: '#a8e6cf' }}>Drift paused — personality held at its current state.</div>
          )}
        </Section>

        {/* ── Behavior mode + emotion reason (live) ─────────────────────── */}
        {mode && (
          <Section title="Behavior mode" icon="🎯" accent={modeMeta.color}>
            <div style={{ fontSize: '0.72rem', color: '#e8f6ff', marginBottom: 4 }}>
              {modeMeta.label} · focus <b>{fmtPct(synoptic?.behavior_mode?.focus_level)}</b> · urgency <b>{fmtPct(synoptic?.behavior_mode?.urgency_level)}</b>
            </div>
            <div style={{ fontSize: '0.62rem', color: 'rgba(255,255,255,0.45)', lineHeight: 1.4 }}>
              {synoptic?.behavior_mode?.speech?.pace ? `speech pace ×${synoptic.behavior_mode.speech.pace.toFixed(2)} · energy ${fmtPct(synoptic.behavior_mode.speech.energy)}` : ''}
            </div>
            {reason && (
              <div style={{ marginTop: 8, padding: '0.5rem', borderRadius: 8, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}>
                <div style={{ fontSize: '0.6rem', letterSpacing: '1px', textTransform: 'uppercase', color: 'rgba(255,255,255,0.4)', marginBottom: 3 }}>💬 why she reacted</div>
                <div style={{ fontSize: '0.68rem', color: '#e8f6ff', fontStyle: 'italic', lineHeight: 1.4 }}>“{reason.hedged}”</div>
                <div style={{ fontSize: '0.6rem', color: 'rgba(255,255,255,0.35)', marginTop: 3 }}>
                  {reason.drivers.map((d) => `${d.signal} ${fmtPct(d.value)}`).join(' · ')}
                </div>
              </div>
            )}
          </Section>
        )}

        {/* ── Trait Activation Engine (live) ────────────────────────────── */}
        {traitEngine && (
          <Section title="Trait engine" icon="🎭" accent="#a3e635">
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginBottom: 8 }}>
              {(traitEngine.active_traits || []).map((t) => (
                <span key={t.id} style={{
                  padding: '3px 9px', borderRadius: 999, fontSize: '0.62rem', fontWeight: 800,
                  color: t.color, border: `1px solid ${t.color}66`, background: `${t.color}18`,
                }}>
                  {t.label}
                </span>
              ))}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 1rem' }}>
              {[['focus_level', 'focus'], ['urgency_level', 'urgency'], ['empathy_level', 'empathy'], ['confidence_level', 'confidence'], ['cognitive_load', 'load'], ['engagement_level', 'engagement'], ['system_stability', 'stability']].map(([k, label]) => {
                const v = Math.max(0, Math.min(1, traitEngine.latent?.[k] ?? 0));
                return (
                  <div key={k} style={{ marginBottom: '0.35rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.6rem', marginBottom: 2 }}>
                      <span style={{ color: 'rgba(255,255,255,0.6)' }}>{label}</span>
                      <span style={{ color: '#a3e635', fontWeight: 700 }}>{Math.round(v * 100)}%</span>
                    </div>
                    <div style={{ height: 4, background: 'rgba(255,255,255,0.08)', borderRadius: 2, overflow: 'hidden' }}>
                      <div style={{ width: `${Math.round(v * 100)}%`, height: '100%', background: '#a3e63588', borderRadius: 2, transition: 'width 0.6s ease' }} />
                    </div>
                  </div>
                );
              })}
            </div>
            {traitEngine.voice && (
              <div style={{ marginTop: 8, padding: '0.45rem', borderRadius: 8, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', fontSize: '0.62rem', color: 'rgba(255,255,255,0.65)' }}>
                🎙️ rate <b style={{ color: '#e8f6ff' }}>×{traitEngine.voice.speech_rate.toFixed(2)}</b> · pitch {traitEngine.voice.pitch.toFixed(2)} · volume {Math.round(traitEngine.voice.volume * 100)}% · pause {traitEngine.voice.pause_duration.toFixed(2)}s
                <div style={{ fontSize: '0.58rem', color: 'rgba(255,255,255,0.4)', marginTop: 2 }}>{traitEngine.voice.pauses}</div>
              </div>
            )}
            {traitEngine.avatar && (
              <div style={{ marginTop: 6, fontSize: '0.6rem', color: 'rgba(255,255,255,0.45)' }}>
                👤 smile {Math.round(traitEngine.avatar.Smile * 100)}% · head {traitEngine.avatar.HeadTilt.toFixed(1)}° · gaze {Math.round(traitEngine.avatar.EyeFocus * 100)}% · posture {Math.round(traitEngine.avatar.Posture * 100)}% · blink {traitEngine.avatar.BlinkRate.toFixed(2)}
              </div>
            )}
          </Section>
        )}

        {/* ── Transparency Satisfaction ──────────────────────────────────── */}
        {transparency && (
          <Section title="Transparency satisfaction" icon="🔍" accent={transparency.dial_back ? '#ff9a9e' : '#34d399'}>
            <HealthGauge
              label="Did my behavior make sense?"
              value={transparency.transparency_satisfaction}
              color={transparency.dial_back ? '#ff9a9e' : transparency.transparency_satisfaction > 0.6 ? '#34d399' : '#ffd93d'}
              icon="🪞"
            />
            {transparency.dial_back && (
              <div style={{ fontSize: '0.62rem', color: '#ffb3b3', marginTop: 2, lineHeight: 1.4 }}>
                ⛔ {transparency.reason} — I'm dialing back intensity and initiative.
              </div>
            )}
            <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
              {[0.2, 0.5, 0.8].map((r) => (
                <button
                  key={r}
                  onClick={() => run('feedback', () => api('/feedback', {
                    method: 'POST',
                    body: JSON.stringify({ user_id: 'user_default', rating: r, discomfort: r === 0.2 }),
                  }))}
                  style={{
                    flex: 1, padding: '0.35rem 0.2rem', borderRadius: 8, cursor: 'pointer',
                    fontSize: '0.62rem', fontWeight: 700,
                    border: r === 0.2 ? '1px solid #ff9a9e66' : '1px solid rgba(255,255,255,0.14)',
                    background: r === 0.2 ? 'rgba(255,154,158,0.12)' : 'rgba(255,255,255,0.04)',
                    color: r === 0.2 ? '#ffb3b3' : '#e8f6ff',
                  }}
                >
                  {r === 0.2 ? '🙁 unclear' : r === 0.5 ? '😐 mostly' : '😊 clear'}
                </button>
              ))}
            </div>
          </Section>
        )}

        {/* ── Companion health ──────────────────────────────────────────── */}
        <Section title="Relationship health" icon="💚" accent={latest.stability_index > 0.6 ? '#a8e6cf' : latest.stability_index > 0.4 ? '#ffd93d' : '#ff9a9e'}>
          <HealthGauge
            label="Stability Index"
            value={latest.stability_index}
            color={latest.stability_index > 0.6 ? '#a8e6cf' : latest.stability_index > 0.4 ? '#ffd93d' : '#ff9a9e'}
            hint={trend.stability_index ? `trend ${trend.stability_index}` : undefined}
            icon="🛡️"
          />
          <HealthGauge
            label="Over-Attachment Risk"
            value={latest.over_attachment_risk}
            color={latest.over_attachment_risk > 0.55 ? '#ff9a9e' : latest.over_attachment_risk > 0.3 ? '#ffd93d' : '#a8e6cf'}
            hint={latest.reliance_signals ? `${latest.reliance_signals} reliance signal(s) · ${fmtDays(latest.absent_days)} since last visit` : `no reliance signals · ${fmtDays(latest.absent_days)} since last visit`}
            icon="🫂"
          />
          {reviewer.tone_appropriateness != null && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 1rem', marginTop: '0.3rem' }}>
              <HealthGauge label="Tone" value={reviewer.tone_appropriateness} color="#6bcbef" icon="🎙️" />
              <HealthGauge label="Boundaries" value={reviewer.boundary_respect} color="#c084fc" icon="🧱" />
              <HealthGauge label="Engagement" value={reviewer.engagement} color="#00f2ff" icon="✨" />
              <HealthGauge label="Reassurance" value={reviewer.reassurance} color="#a8e6cf" icon="🕊️" />
            </div>
          )}
        </Section>
      </div>
    </DraggablePanel>
  );
}

function btnStyle(busyFlag) {
  return {
    flex: 1, padding: '0.42rem 0.3rem', borderRadius: 8, cursor: busyFlag ? 'wait' : 'pointer',
    fontSize: '0.66rem', fontWeight: 700, border: '1px solid rgba(255,255,255,0.14)',
    background: 'rgba(255,255,255,0.05)', color: '#e8f6ff', transition: 'all 0.2s', opacity: busyFlag ? 0.5 : 1,
    whiteSpace: 'nowrap',
  };
}
