import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import useStore from '../store';

// ── Behavior-mode palette ─────────────────────────────────────────────────────
// Same language as the dashboard (GovernancePanel MODE_META + AnalyticsDashboard
// Companion Presence), so every web surface renders the mode identically.
const MODE_META = {
  CALM:    { color: '#6bcbef', label: 'Calm' },
  STEALTH: { color: '#a78bfa', label: 'Stealth' },
  COMBAT:  { color: '#ff6b6b', label: 'Combat' },
};
const DEFAULT_META = MODE_META.CALM;

/// Behavior-mode accent color — shared by the chip and the summary popover.
export function modeColor(mode) {
  return (MODE_META[(mode || '').toUpperCase()] || DEFAULT_META).color;
}

// ── Numeric guards (server values always parse, but be defensive) ─────────────
const clamp01 = (v) => Math.max(0, Math.min(1, Number.isFinite(v) ? v : 0));
const pct = (v) => `${Math.round(clamp01(v) * 100)}%`;
const num = (v, d = 2) => (Number.isFinite(Number(v)) ? Number(v).toFixed(d) : '—');
const pctN = (v) => (Number.isFinite(Number(v)) ? `${Math.round(Number(v) * 100)}%` : '—');
const humanize = (id) =>
  (id || '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

// The 7 latent intensities + their short labels (mirrors GovernancePanel).
const LATENT_ROWS = [
  ['focus_level', 'focus'],
  ['urgency_level', 'urgency'],
  ['empathy_level', 'empathy'],
  ['confidence_level', 'confidence'],
  ['cognitive_load', 'load'],
  ['engagement_level', 'engagement'],
  ['system_stability', 'stability'],
];

function Bar({ value, color }) {
  return (
    <div style={{
      height: 5, borderRadius: 3, background: 'rgba(255,255,255,0.08)', overflow: 'hidden',
    }}>
      <div style={{
        width: pct(value), height: '100%', background: color,
        boxShadow: `0 0 8px ${color}`, borderRadius: 3, transition: 'width 0.4s ease',
      }} />
    </div>
  );
}

function Row({ label, value, color }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      fontSize: 10, fontFamily: 'monospace', marginBottom: 4,
    }}>
      <span style={{ color: 'rgba(255,255,255,0.5)', letterSpacing: 1 }}>{label}</span>
      <span style={{ color: color || '#9d6bff', fontWeight: 700 }}>{value}</span>
    </div>
  );
}

function SectionLabel({ text, color = '#00d2ff' }) {
  return (
    <div style={{
      fontSize: 9, letterSpacing: 1.5, fontFamily: 'monospace', fontWeight: 700,
      color, marginBottom: 8, borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: 4,
    }}>
      {text}
    </div>
  );
}

/// Compact presence pill for the orb home screen — Aariya's real behavior mode
/// + active-trait count from the live synoptic (the same `trait_engine` bundle
/// the Governance / Analytics panels read). Nothing fabricated: with no synoptic
/// yet it renders a neutral awaiting state, never an implied CALM. Tap opens the
/// full presence panel — trait engine (latents, arbitration, voice/avatar/UI),
/// transparency, and relationship health — portaled to document.body so it can
/// never be clipped by the draggable header panel or occluded by scene overlays.
export default function PresenceChip() {
  const synoptic = useStore((s) => s.synoptic) || {};
  const trust = useStore((s) => s.trust);
  const chipRef = useRef(null);
  const [open, setOpen] = useState(false);       // panel mounted (incl. exit)
  const [closing, setClosing] = useState(false); // exit animation in progress
  const [anchor, setAnchor] = useState(null);    // { left, top } — chip rect at open

  const te = synoptic.trait_engine || {};
  const bm = synoptic.behavior_mode || {};
  const mode = te.mode || bm.mode || '';
  const traits = Array.isArray(te.active_traits) ? te.active_traits : [];
  const swaps = Array.isArray(te.arbitration) ? te.arbitration : [];
  const hasData = mode !== '';
  const meta = MODE_META[mode.toUpperCase()] || DEFAULT_META;
  // Neutral color is a hex so the 8-digit-alpha suffix stays valid in the
  // awaiting state (rgba + "1f" would be invalid CSS and drop the pill chrome).
  const color = hasData ? modeColor(mode) : '#9aa4b2';

  const latent = te.latent || {};
  const voice = te.voice || {};
  const avatar = te.avatar || {};
  const ui = te.ui || {};

  const trans = synoptic.transparency || synoptic.companion_health?.transparency || null;
  const satisfaction = trans?.transparency_satisfaction ?? 0.5;
  const dialBack = trans?.dial_back === true;
  const redline = trans?.redline === true;
  const health = synoptic.companion_health || {};
  const stability = health.stability_index ?? 0.5;
  const attachRisk = health.over_attachment_risk ?? 0;

  const requestClose = () => {
    if (open && !closing) setClosing(true);
  };

  const toggle = () => {
    // Re-open while the exit animation runs → cancel the close.
    if (closing) {
      setClosing(false);
      return;
    }
    if (open) {
      requestClose();
      return;
    }
    const rect = chipRef.current?.getBoundingClientRect();
    // Clamp the panel top so it never runs past the viewport bottom (the chip
    // lives in a draggable header the user can pull low), and size its max
    // height from the space actually available below the anchor.
    const gap = 8;
    const top = rect
      ? Math.min(rect.bottom + gap, Math.max(80, window.innerHeight - 300))
      : 80;
    const maxH = Math.max(240, Math.min(620, window.innerHeight - top - 12));
    setAnchor({
      left: rect?.left ?? 32,
      top,
      maxH,
    });
    setOpen(true);
  };

  // Unmount the panel only after its exit animation finishes (150ms CSS out).
  useEffect(() => {
    if (!closing) return;
    const t = setTimeout(() => {
      setClosing(false);
      setOpen(false);
    }, 180);
    return () => clearTimeout(t);
  }, [closing]);

  // Escape closes the panel (it's a portaled fixed overlay, not a modal).
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === 'Escape' && !closing) setClosing(true);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, closing]);

  return (
    <div style={{ display: 'inline-block', marginTop: 10 }}>
      <button
        ref={chipRef}
        onClick={toggle}
        aria-expanded={open}
        title={hasData ? `${meta.label} · ${traits.length} active traits` : 'Awaiting presence'}
        style={{
          display: 'flex', alignItems: 'center', gap: 7, cursor: 'pointer',
          padding: '5px 12px', borderRadius: 18,
          background: `${color}1f`, border: `1px solid ${color}73`,
          color, fontFamily: 'inherit', fontSize: 10.5, fontWeight: 800,
          letterSpacing: 0.8, transition: 'all 0.25s ease',
          boxShadow: hasData ? `0 0 12px ${color}33` : 'none',
        }}
        onMouseOver={(e) => {
          e.currentTarget.style.background = `${color}2e`;
          e.currentTarget.style.boxShadow = hasData ? `0 0 18px ${color}55` : 'none';
        }}
        onMouseOut={(e) => {
          e.currentTarget.style.background = `${color}1f`;
          e.currentTarget.style.boxShadow = hasData ? `0 0 12px ${color}33` : 'none';
        }}
      >
        <span style={{
          width: 7, height: 7, borderRadius: '50%', background: color, flexShrink: 0,
          boxShadow: hasData ? `0 0 6px ${color}` : 'none',
        }} />
        {hasData ? `${mode.toUpperCase()} · ${traits.length}` : '···'}
      </button>

      {open && createPortal(
        <>
          {/* Fade+scale keyframes (scoped, self-contained — panel + backdrop). */}
          <style>{`
            @keyframes ariPopIn { from { opacity: 0; transform: scale(0.94) translateY(-6px); } to { opacity: 1; transform: scale(1) translateY(0); } }
            @keyframes ariPopOut { from { opacity: 1; transform: scale(1) translateY(0); } to { opacity: 0; transform: scale(0.96) translateY(-3px); } }
            @keyframes ariFadeIn { from { opacity: 0; } to { opacity: 1; } }
            @keyframes ariFadeOut { from { opacity: 1; } to { opacity: 0; } }
            .ari-pop-in { animation: ariPopIn 170ms cubic-bezier(0.2, 0.9, 0.3, 1.15); transform-origin: top left; }
            .ari-pop-out { animation: ariPopOut 150ms ease-in forwards; transform-origin: top left; }
            .ari-backdrop-in { animation: ariFadeIn 170ms ease-out; }
            .ari-backdrop-out { animation: ariFadeOut 150ms ease-in forwards; }
            @media (prefers-reduced-motion: reduce) {
              .ari-pop-in, .ari-pop-out, .ari-backdrop-in, .ari-backdrop-out { animation: none; }
            }
          `}</style>
          {/* Click-away backdrop — viewport-wide, above everything except the panel */}
          <div
            className={closing ? 'ari-backdrop-out' : 'ari-backdrop-in'}
            style={{ position: 'fixed', inset: 0, zIndex: 2000, cursor: 'default' }}
            onClick={requestClose}
          />
          <div
            role="dialog"
            aria-label="Aariya presence"
            className={closing ? 'ari-pop-out' : 'ari-pop-in'}
            style={{
            position: 'fixed', left: anchor?.left ?? 32, top: anchor?.top ?? 80, zIndex: 2001,
            width: 340, maxHeight: anchor?.maxH ?? 'min(72vh, 620px)', overflowY: 'auto',
            overscrollBehavior: 'contain', padding: 16, borderRadius: 12,
            background: 'rgba(6, 6, 18, 0.95)', backdropFilter: 'blur(14px)',
            border: `1px solid ${color}55`, boxShadow: '0 16px 48px rgba(0,0,0,0.65)',
            display: 'flex', flexDirection: 'column', gap: 14,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{
                fontSize: 10, color: '#00d2ff', fontWeight: 800, letterSpacing: 2,
                fontFamily: 'monospace',
              }}>
                AARIYA · PRESENCE
              </span>
              {hasData && (
                <span style={{
                  padding: '2px 9px', borderRadius: 999, fontSize: 9.5, fontWeight: 800,
                  letterSpacing: 1, color: meta.color, border: `1px solid ${meta.color}66`,
                  background: `${meta.color}18`,
                }}>
                  {meta.label.toUpperCase()}
                </span>
              )}
            </div>

            {!hasData ? (
              <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)' }}>
                Awaiting first brain turn…
              </span>
            ) : (
              <>
                {/* ── Trait engine (full) ──────────────────────────────────── */}
                <div>
                  <SectionLabel text="🎭 TRAIT ENGINE" color="#a3e635" />
                  {traits.length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
                      {traits.map((t) => {
                        const tc = typeof t.color === 'string' && t.color.startsWith('#') ? t.color : '#00d2ff';
                        return (
                          <span key={t.id || t.label} style={{
                            padding: '3px 9px', borderRadius: 9, fontSize: 10, fontWeight: 700,
                            color: tc, border: `1px solid ${tc}66`, background: `${tc}18`,
                          }}>
                            {t.label || humanize(t.id)}
                          </span>
                        );
                      })}
                    </div>
                  )}

                  {/* Situational arbitration — why a trait swapped in */}
                  {swaps.length > 0 && (
                    <div style={{ marginBottom: 10, padding: '6px 9px', borderRadius: 8, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}>
                      {swaps.map((s, i) => (
                        <div key={i} style={{ fontSize: 9.5, fontFamily: 'monospace', color: 'rgba(255,255,255,0.7)', marginBottom: i < swaps.length - 1 ? 4 : 0 }}>
                          <span style={{ color: '#ff8fa3', fontWeight: 700 }}>{humanize(s.trait)}</span>
                          {' ⇢ '}
                          <span style={{ textDecoration: 'line-through', color: 'rgba(255,255,255,0.35)' }}>{humanize(s.replaced)}</span>
                          <span style={{ color: 'rgba(255,255,255,0.45)' }}> — {s.reason}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Latent intensities — 2-col grid */}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 1rem' }}>
                    {LATENT_ROWS.map(([k, label]) => {
                      const v = Math.max(0, Math.min(1, latent[k] ?? 0));
                      return (
                        <div key={k} style={{ marginBottom: '0.4rem' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, marginBottom: 2 }}>
                            <span style={{ color: 'rgba(255,255,255,0.55)', fontFamily: 'monospace' }}>{label}</span>
                            <span style={{ color: '#a3e635', fontWeight: 700, fontFamily: 'monospace' }}>{Math.round(v * 100)}%</span>
                          </div>
                          <div style={{ height: 4, background: 'rgba(255,255,255,0.08)', borderRadius: 2, overflow: 'hidden' }}>
                            <div style={{ width: `${Math.round(v * 100)}%`, height: '100%', background: '#a3e63588', borderRadius: 2, transition: 'width 0.5s ease' }} />
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* Voice / avatar / UI parameter readouts */}
                  {Object.keys(voice).length > 0 && (
                    <div style={{ marginTop: 10, padding: '7px 9px', borderRadius: 8, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', fontSize: 9.5, fontFamily: 'monospace', color: 'rgba(255,255,255,0.65)' }}>
                      🎙️ rate <b style={{ color: '#e8f6ff' }}>×{num(voice.speech_rate)}</b> · pitch {num(voice.pitch)} · volume {pctN(voice.volume)} · pause {num(voice.pause_duration)}s{voice.silence_bias > 0 ? ' · 🔇 silence bias' : ''}
                      {voice.pauses && (
                        <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.4)', marginTop: 2 }}>{voice.pauses}</div>
                      )}
                    </div>
                  )}
                  {Object.keys(avatar).length > 0 && (
                    <div style={{ marginTop: 5, fontSize: 9, fontFamily: 'monospace', color: 'rgba(255,255,255,0.45)' }}>
                      👤 smile {pctN(avatar.Smile)} · head {num(avatar.HeadTilt)}° · gaze {pctN(avatar.EyeFocus)} · posture {pctN(avatar.Posture)} · blink {num(avatar.BlinkRate)}
                    </div>
                  )}
                  {Object.keys(ui).length > 0 && (
                    <div style={{ marginTop: 5, fontSize: 9, fontFamily: 'monospace', color: 'rgba(255,255,255,0.45)' }}>
                      🖥️ ui: progress {pctN(ui.progress_bar)} · suggestions {ui.highlighted_suggestions ? '✓' : '—'} · monitor {ui.monitoring_status ? '●' : '○'} · tone {pctN(ui.color_tone)}
                    </div>
                  )}
                </div>

                {/* ── Transparency (full, honest when data is present) ────── */}
                <div>
                  <SectionLabel text="🔍 TRANSPARENCY" color={dialBack ? '#ff9a9e' : '#34d399'} />
                  {trans ? (
                    <>
                      <Row
                        label="DID MY BEHAVIOR MAKE SENSE?"
                        value={pct(satisfaction)}
                        color={dialBack ? '#ff6b6b' : satisfaction > 0.6 ? '#34d399' : '#ffd93d'}
                      />
                      <Bar value={satisfaction} color={dialBack ? '#ff6b6b' : satisfaction > 0.6 ? '#34d399' : '#ffd93d'} />
                      <div style={{ display: 'flex', gap: 14, marginTop: 6, fontSize: 9, fontFamily: 'monospace' }}>
                        <span style={{ color: 'rgba(255,255,255,0.45)' }}>
                          explicit <b style={{ color: trans.explicit_rating != null ? '#34d399' : 'rgba(255,255,255,0.25)' }}>
                            {trans.explicit_rating != null ? Number(trans.explicit_rating).toFixed(2) : '—'}
                          </b>
                        </span>
                        <span style={{ color: 'rgba(255,255,255,0.45)' }}>
                          implicit <b style={{ color: '#00d2ff' }}>{num(trans.implicit_rating)}</b>
                        </span>
                        <span style={{ color: 'rgba(255,255,255,0.45)' }}>
                          feedback <b style={{ color: 'rgba(255,255,255,0.7)' }}>{trans.feedback_count ?? 0}</b>
                        </span>
                      </div>
                      {dialBack && (
                        <div style={{ marginTop: 6, fontSize: 9.5, color: '#ffb3b3', lineHeight: 1.4 }}>
                          ⛔ {redline ? 'Red-line — ' : ''}{trans.reason || 'Dialed back — lowering intensity until you say it\'s fine'}
                        </div>
                      )}
                    </>
                  ) : (
                    <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)' }}>
                      No transparency reading this turn yet
                    </span>
                  )}
                </div>

                {/* ── Relationship health ──────────────────────────────────── */}
                <div>
                  <SectionLabel text="🤝 RELATIONSHIP HEALTH" color="#7c5cff" />
                  <Row
                    label="STABILITY"
                    value={pct(stability)}
                    color={stability >= 0.7 ? '#34d399' : stability >= 0.4 ? '#ffd93d' : '#ff6b6b'}
                  />
                  <Bar value={stability} color={stability >= 0.7 ? '#34d399' : stability >= 0.4 ? '#ffd93d' : '#ff6b6b'} />
                  <div style={{ marginTop: 8 }}>
                    <Row
                      label="ATTACH RISK"
                      value={pct(attachRisk)}
                      color={attachRisk >= 0.6 ? '#ff6b6b' : attachRisk >= 0.3 ? '#ffd93d' : '#2dd4bf'}
                    />
                    <Bar value={attachRisk} color={attachRisk >= 0.6 ? '#ff6b6b' : attachRisk >= 0.3 ? '#ffd93d' : '#2dd4bf'} />
                  </div>
                  <div style={{ marginTop: 8 }}>
                    <Row label="TRUST" value={pct(trust)} color="#7c5cff" />
                    <Bar value={trust} color="#7c5cff" />
                  </div>
                </div>

              </>
            )}

            <span style={{
              fontSize: 9, color: 'rgba(255,255,255,0.22)', fontFamily: 'monospace', letterSpacing: 0.5,
            }}>
              details in the Governance panel
            </span>
          </div>
        </>,
        document.body,
      )}
    </div>
  );
}
