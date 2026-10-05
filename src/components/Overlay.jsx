import React, { useState, useRef, useEffect, useCallback } from 'react';
import useStore from '../store';
import DraggablePanel from './DraggablePanel';
import PresenceChip from './PresenceChip';
import GEVPanel from './GEVPanel';
import { apiBase } from '../utils/apiHost';
import { isCaptureAllowed, setCaptureEnabled, onCaptureChange } from '../utils/privacySwitches';

// ── Mood palette — aurora-tinted per emotion ─────────────────────────────────
const moodColors = {
  happy:    '#34d399',
  excited:  '#fbbf24',
  calm:     '#38bdf8',
  neutral:  '#94a3b8',
  confused: '#e879f9',
  tired:    '#818cf8',
  stressed: '#fb7185',
  sad:      '#60a5fa',
  angry:    '#f87171',
  focused:  '#22d3ee',
  bored:    '#6b7280',
  anxious:  '#fb923c',
};

// ── Shared micro-styles ───────────────────────────────────────────────────────
const ROW_STYLE = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  marginBottom: '2px',
  fontSize: '0.72rem',
  textTransform: 'capitalize',
  color: 'rgba(241,245,249,0.7)',
};

const TRACK_STYLE = {
  width: '100%', height: '4px',
  background: 'rgba(255,255,255,0.07)',
  borderRadius: '4px', overflow: 'hidden',
};

function MoodBar({ value, color }) {
  return (
    <div style={TRACK_STYLE}>
      <div style={{
        width: `${Math.round(value * 100)}%`,
        height: '100%',
        background: color,
        borderRadius: '4px',
        boxShadow: `0 0 6px ${color}88`,
        transition: 'width 0.45s cubic-bezier(0.4,0,0.2,1)',
      }} />
    </div>
  );
}

function StatusDot({ active, color }) {
  return (
    <span style={{
      display: 'inline-block',
      width: 8, height: 8,
      borderRadius: '50%',
      marginRight: 8,
      flexShrink: 0,
      background: active ? (color || '#34d399') : 'rgba(255,255,255,0.15)',
      boxShadow: active ? `0 0 8px ${color || '#34d399'}, 0 0 16px ${color || '#34d399'}44` : 'none',
      transition: 'all 0.3s ease',
    }} />
  );
}

// ── Send icon ─────────────────────────────────────────────────────────────────
function SendIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
         style={{ marginLeft: '-1px' }}>
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  );
}

// ── Settings gear icon ────────────────────────────────────────────────────────
function GearIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

// ── Chat icon ─────────────────────────────────────────────────────────────────
function ChatIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  );
}


// ── System-wide privacy switches (ToDo §5) ────────────────────────────────────
// Two buttons that close the microphone and the camera for the WHOLE app —
// not just the panel they sit in. State mirrors src/utils/privacySwitches.js,
// which is the thing actually enforcing capture; this is the readout.
function PrivacySwitches() {
  const [capture, setCapture] = useState({
    microphone: isCaptureAllowed('microphone'),
    camera: isCaptureAllowed('camera'),
  });

  useEffect(() => onCaptureChange(setCapture), []);

  const toggle = (kind) => setCaptureEnabled(kind, !capture[kind]);

  return (
    <div className="privacy-switches" role="group" aria-label="Privacy switches">
      <button
        type="button"
        className={`privacy-switch-btn ${capture.microphone ? '' : 'blocked'}`}
        onClick={() => toggle('microphone')}
        aria-pressed={!capture.microphone}
        title={capture.microphone ? 'Mute the microphone system-wide' : 'Microphone is muted system-wide'}
      >
        {capture.microphone ? '\u{1F3A4} Mic On' : '\u{1F507} Mic Off'}
      </button>
      <button
        type="button"
        className={`privacy-switch-btn ${capture.camera ? '' : 'blocked'}`}
        onClick={() => toggle('camera')}
        aria-pressed={!capture.camera}
        title={capture.camera ? 'Close the camera system-wide' : 'Camera is closed system-wide'}
      >
        {capture.camera ? '\u{1F4F7} Cam On' : '\u{1F512} Cam Off'}
      </button>
    </div>
  );
}

export default function Overlay() {
  const {
    started, listening, speaking, chatHistory, submitText,
    voicePitch, setVoicePitch, voiceRate, setVoiceRate, thinking, faceDetected, emotions, userEmotion,
    showChatPanel, showMoodPanel, showUserMoodPanel, showStatusPanel, showVoiceLabPanel,
    toggleChatPanel, toggleMoodPanel, toggleUserMoodPanel, toggleStatusPanel, toggleVoiceLabPanel,
    showBrainMonitor, toggleBrainMonitor,
    showNewsPanel, toggleNewsPanel,
    showAutonomyPanel, toggleAutonomyPanel,
    showGovernancePanel, toggleGovernancePanel,
    showGevPanel, toggleGevPanel,
  } = useStore();

  const [inputValue, setInputValue]   = useState('');
  const [showSettings, setShowSettings] = useState(false);
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const chatEndRef = useRef(null);

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory]);

  // Check voice availability
  useEffect(() => {
    fetch(`${apiBase()}/api/system/health`)
      .then(res => res.json())
      .then(data => {
        const checks  = Array.isArray(data?.checks) ? data.checks : [];
        const vc      = checks.find(c => c.name === 'voice');
        const status  = vc?.status;
        const meta    = vc?.meta || {};
        const whisperUp = meta.whisper !== false && meta.whisper !== undefined;
        const vadUp     = meta.vad    !== false && meta.vad    !== undefined;
        if (status === 'down' || status === 'unknown' || !whisperUp || !vadUp) {
          setVoiceEnabled(false);
        }
      })
      .catch(() => {/* silent — voice banner not critical */});
  }, []);

  const handleSubmit = useCallback((e) => {
    e.preventDefault();
    if (!inputValue.trim()) return;
    submitText(inputValue);
    setInputValue('');
  }, [inputValue, submitText]);

  // ── Emotion helpers ────────────────────────────────────────────────────────
  const defaultEmotion  = { valence: 0, arousal: 0, primary: 'neutral' };
  const safeEmotion     = userEmotion || defaultEmotion;
  const computedValence = isNaN(safeEmotion.valence) ? 0 : Math.max(-1, Math.min(1, safeEmotion.valence));
  const computedArousal = isNaN(safeEmotion.arousal) ? 0 : Math.max( 0, Math.min(1, safeEmotion.arousal));

  const getUserMoods = () => {
    const moods = { [safeEmotion.primary || 'neutral']: 0.8 };
    if (computedArousal > 0.5 && computedValence >  0.3) moods.excited = Math.min(computedArousal * computedValence, 1);
    if (computedArousal < 0.4 && computedValence >  0.2) moods.calm    = Math.min((1 - computedArousal) * 0.5, 1);
    if (computedArousal > 0.6 && computedValence < -0.2) moods.stressed = Math.min(computedArousal * Math.abs(computedValence), 1);
    if (computedArousal < 0.3 && computedValence <  0  ) moods.tired   = Math.min((1 - computedArousal) * 0.4, 1);
    if (computedArousal > 0.3 && computedArousal < 0.7 && Math.abs(computedValence) < 0.3) moods.focused = 0.4;
    Object.keys(moods).forEach(k => { if (isNaN(moods[k])) moods[k] = 0; });
    return moods;
  };

  const userMoods = getUserMoods();

  return (
    <div className="overlay">

      {/* ── HEADER — Draggable brand panel ─────────────────────────────────── */}
      <DraggablePanel
        id="aariya_header"
        defaultPosition={{ x: 28, y: 28 }}
        autoHeight={true}
        className="ui-panel"
        style={{ minWidth: 180, padding: '1rem 1.2rem 0.9rem' }}
      >
        <h1 className="drag-handle aariya-brand-name">AARIYA</h1>
        <div className="drag-handle aariya-subtitle">Anime Companion</div>
        <PresenceChip />
      </DraggablePanel>

      {/* GEV Panel */}
      {showGevPanel && <GEVPanel />}

      {/* ── CHAT PANEL — Draggable ─────────────────────────────────────────── */}
      {showChatPanel && (
        <DraggablePanel
          id="aariya_chat"
          defaultPosition={{ x: 28, y: 148 }}
          defaultSize={{ width: '370px', height: '520px' }}
          className="ui-panel chat-panel"
        >
          {/* Title bar */}
          <div className="drag-handle panel-title-bar">
            <ChatIcon />
            Chat Stream
          </div>

          {/* Message history */}
          <div style={{
            flex: 1, overflowY: 'auto', padding: '1rem',
            display: 'flex', flexDirection: 'column', gap: '0.6rem',
          }} className="scrollbar-hide">
            {chatHistory.length === 0 && (
              <div style={{
                textAlign: 'center', color: 'var(--text-muted)',
                marginTop: '40%', fontStyle: 'italic', fontSize: '0.85rem',
                animation: 'fadeIn 0.6s ease',
              }}>
                Say something or type a message ✨
              </div>
            )}

            {chatHistory.map((msg, i) =>
              msg.role === 'thought' ? (
                <div key={i} className="msg-thought" style={{ animation: 'fadeIn 0.5s ease forwards' }}>
                  <span style={{ opacity: 0.6, marginRight: 6 }}>💭</span>
                  {msg.text}
                </div>
              ) : (
                <div key={i} style={{
                  alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                  padding: '0.7rem 1rem',
                  borderRadius: '14px',
                  maxWidth: '86%',
                  fontSize: '0.9rem',
                  lineHeight: '1.45',
                  backdropFilter: 'blur(8px)',
                  animation: 'fadeIn 0.3s ease forwards',
                  ...(msg.role === 'user' ? {
                    background: 'rgba(129, 140, 248, 0.1)',
                    border: '1px solid rgba(129, 140, 248, 0.18)',
                    borderBottomRightRadius: 4,
                    color: 'var(--text-primary)',
                  } : {
                    background: 'linear-gradient(135deg, rgba(192,132,252,0.12), rgba(244,114,182,0.06))',
                    border: '1px solid rgba(192, 132, 252, 0.18)',
                    borderTopLeftRadius: 4,
                    boxShadow: '0 4px 20px rgba(192,132,252,0.08)',
                    color: 'var(--text-primary)',
                  }),
                }}>
                  <span style={{
                    fontSize: '0.6rem',
                    opacity: 0.75,
                    display: 'block',
                    marginBottom: 5,
                    textTransform: 'uppercase',
                    letterSpacing: '1.5px',
                    fontWeight: 700,
                    fontFamily: 'var(--font-display)',
                    color: msg.role === 'bot' ? 'var(--primary)' : '#86efac',
                  }}>
                    {msg.role === 'user' ? 'You' : msg.proactive ? '💫 Aariya · proactive' : 'Aariya'}
                    {msg.streaming && (
                      <span style={{ marginLeft: 6, fontWeight: 400, opacity: 0.6 }}>…</span>
                    )}
                  </span>
                  {msg.text}
                  {msg.proactive && (
                    <span style={{
                      display: 'block', marginTop: 6,
                      fontSize: '0.58rem', color: 'rgba(56,189,248,0.65)',
                      letterSpacing: '1px', textTransform: 'uppercase',
                    }}>
                      ✦ she reached out on her own
                    </span>
                  )}
                </div>
              )
            )}
            <div ref={chatEndRef} />
          </div>

          {/* Input area */}
          <form onSubmit={handleSubmit} style={{
            padding: '0.75rem',
            borderTop: '1px solid rgba(192,132,252,0.1)',
            background: 'rgba(0,0,0,0.25)',
            display: 'flex',
            gap: '8px',
            alignItems: 'center',
          }}>
            <input
              type="text"
              value={inputValue}
              onChange={e => setInputValue(e.target.value)}
              placeholder="Type your message…"
              className="chat-input"
            />
            <button type="submit" className="chat-send-btn" aria-label="Send message">
              <SendIcon />
            </button>
          </form>
        </DraggablePanel>
      )}

      {/* ── AI CONTROL CENTER BUTTON ───────────────────────────────────────── */}
      <button
        className="control-center-btn"
        onClick={() => {
          if (window.electronAPI?.openAnalytics) {
            window.electronAPI.openAnalytics();
          } else {
            window.open('http://localhost:5173/?route=analytics', '_blank', 'width=1200,height=800');
          }
        }}
      >
        <GearIcon />
        AI Control Center
      </button>

      {/* ── SYSTEM-WIDE MIC / CAMERA KILL SWITCHES ───────────────────────── */}
      <PrivacySwitches />

      {/* ── RIGHT PANELS — only when started ──────────────────────────────── */}
      <div style={{
        visibility: started ? 'visible' : 'hidden',
        pointerEvents: started ? 'auto' : 'none',
        position: 'absolute', inset: 0,
      }}>

        {/* ── AARIYA MOOD PANEL ────────────────────────────────────────────── */}
        {showMoodPanel && (
          <DraggablePanel
            id="aariya_mood"
            defaultPosition={{ x: window.innerWidth - 260, y: window.innerHeight - 440 }}
            defaultSize={{ width: '220px' }}
            autoHeight={true}
            className="ui-panel"
            style={{ minWidth: '215px' }}
          >
            <div className="drag-handle drag-handle-mini">⋮⋮ DRAG</div>
            <h3 style={{ margin: '0 0 0.6rem', color: 'var(--primary)', fontSize: '0.8rem',
                          fontFamily: 'var(--font-display)', fontWeight: 700, letterSpacing: 1 }}>
              🎭 Aariya's Mood
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.55rem' }}>
              {Object.entries(emotions).map(([emotion, value]) => {
                if (value < 0.05) return null;
                const color = moodColors[emotion] || 'var(--primary)';
                return (
                  <div key={emotion}>
                    <div style={{ ...ROW_STYLE, color }}>
                      <span style={{ color: 'var(--text-secondary)', textTransform: 'capitalize' }}>{emotion}</span>
                      <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', fontSize: '0.68rem' }}>
                        {Math.round(value * 100)}%
                      </span>
                    </div>
                    <MoodBar value={value} color={color} />
                  </div>
                );
              })}
            </div>
          </DraggablePanel>
        )}

        {/* ── USER MOOD PANEL ──────────────────────────────────────────────── */}
        {showUserMoodPanel && (
          <DraggablePanel
            id="aariya_user_mood"
            defaultPosition={{ x: window.innerWidth - 260, y: window.innerHeight - 270 }}
            defaultSize={{ width: '220px' }}
            autoHeight={true}
            className="ui-panel"
            style={{ minWidth: '215px' }}
          >
            <div className="drag-handle drag-handle-mini">⋮⋮ DRAG</div>
            <h3 style={{ margin: '0 0 0.6rem', color: '#86efac', fontSize: '0.8rem',
                          fontFamily: 'var(--font-display)', fontWeight: 700, letterSpacing: 1 }}>
              👤 Your Mood
            </h3>

            {faceDetected ? (
              <>
                {/* Primary label */}
                <div style={{ fontSize: '0.75rem', marginBottom: '0.6rem',
                               display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--text-muted)' }}>Primary</span>
                  <span style={{
                    fontWeight: 700, fontFamily: 'var(--font-display)',
                    color: moodColors[safeEmotion.primary] || 'white',
                    textTransform: 'uppercase', fontSize: '0.65rem',
                    padding: '2px 8px',
                    background: 'rgba(255,255,255,0.06)',
                    borderRadius: '20px',
                    letterSpacing: 1,
                  }}>
                    {safeEmotion.primary}
                  </span>
                </div>

                {/* Mood bars */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
                  {Object.entries(userMoods).map(([mood, value]) => {
                    if (value < 0.1) return null;
                    const color = moodColors[mood] || '#86efac';
                    return (
                      <div key={mood}>
                        <div style={ROW_STYLE}>
                          <span style={{ color: 'var(--text-secondary)' }}>{mood}</span>
                          <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color }}>
                            {Math.round(value * 100)}%
                          </span>
                        </div>
                        <MoodBar value={value} color={color} />
                      </div>
                    );
                  })}
                </div>

                {/* Valence / Arousal */}
                <div style={{ marginTop: '0.75rem', paddingTop: '0.6rem',
                               borderTop: '1px solid rgba(255,255,255,0.07)' }}>
                  {/* Valence */}
                  <div style={{ fontSize: '0.68rem', marginBottom: '4px',
                                 display: 'flex', justifyContent: 'space-between', color: 'var(--text-muted)' }}>
                    <span>Valence</span>
                    <span style={{ color: computedValence > 0 ? '#86efac' : computedValence < 0 ? '#fb7185' : '#94a3b8' }}>
                      {computedValence > 0 ? '😊' : computedValence < 0 ? '😔' : '😐'}{' '}
                      {Math.round(Math.abs(computedValence) * 100)}%
                    </span>
                  </div>
                  <div style={{ width: '100%', height: '5px', background: 'rgba(255,255,255,0.07)',
                                 borderRadius: '5px', position: 'relative' }}>
                    <div style={{ position: 'absolute', left: '50%', width: '1px',
                                   height: '100%', background: 'rgba(255,255,255,0.2)' }} />
                    <div style={{
                      position: 'absolute',
                      left: computedValence >= 0 ? '50%' : `${50 + computedValence * 50}%`,
                      width: `${Math.abs(computedValence) * 50}%`,
                      height: '100%',
                      background: computedValence >= 0 ? '#86efac' : '#fb7185',
                      borderRadius: '5px',
                      transition: 'all 0.35s ease',
                    }} />
                  </div>

                  {/* Arousal */}
                  <div style={{ fontSize: '0.68rem', marginTop: '0.5rem', marginBottom: '4px',
                                 display: 'flex', justifyContent: 'space-between', color: 'var(--text-muted)' }}>
                    <span>Energy</span>
                    <span style={{ color: `hsl(${180 - computedArousal * 100}, 80%, 65%)` }}>
                      {computedArousal > 0.7 ? '⚡ High' : computedArousal > 0.3 ? '✨ Med' : '😴 Low'}{' '}
                      {Math.round(computedArousal * 100)}%
                    </span>
                  </div>
                  <MoodBar value={computedArousal} color="linear-gradient(90deg, #38bdf8, #fbbf24, #fb7185)" />
                </div>
              </>
            ) : (
              <div style={{ textAlign: 'center', padding: '1.5rem 1rem',
                             color: 'var(--text-muted)', fontSize: '0.82rem' }}>
                <div style={{ fontSize: '1.8rem', marginBottom: '0.4rem', opacity: 0.5 }}>👁️</div>
                No face detected
              </div>
            )}
          </DraggablePanel>
        )}

        {/* ── STATUS PANEL ─────────────────────────────────────────────────── */}
        {showStatusPanel && (
          <DraggablePanel
            id="aariya_status"
            defaultPosition={{ x: window.innerWidth - 260, y: window.innerHeight - 110 }}
            defaultSize={{ width: '200px' }}
            autoHeight={true}
            className="ui-panel"
          >
            <div className="drag-handle drag-handle-mini">⋮⋮ DRAG</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', fontSize: '0.82rem' }}>
                <StatusDot active={listening} />
                <span style={{ color: listening ? '#34d399' : 'var(--text-muted)' }}>
                  {listening ? 'Listening…' : 'Standby'}
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', fontSize: '0.82rem' }}>
                <StatusDot active={speaking} color="var(--primary)" />
                <span style={{ color: speaking ? 'var(--primary)' : 'var(--text-muted)' }}>
                  {speaking ? 'Speaking…' : 'Silent'}
                </span>
              </div>
              {thinking && (
                <div style={{ display: 'flex', alignItems: 'center', fontSize: '0.82rem',
                               animation: 'fadeIn 0.3s ease' }}>
                  <StatusDot active={true} color="#818cf8" />
                  <span style={{ color: '#818cf8' }}>Thinking…</span>
                </div>
              )}
            </div>
          </DraggablePanel>
        )}

        {/* ── VOICE LAB PANEL ──────────────────────────────────────────────── */}
        {voiceEnabled && showVoiceLabPanel && (
          <DraggablePanel
            id="aariya_voicelab"
            defaultPosition={{ x: window.innerWidth - 260, y: 148 }}
            defaultSize={{ width: '220px' }}
            autoHeight={true}
            className="ui-panel"
          >
            <div className="drag-handle drag-handle-mini">⋮⋮ DRAG</div>
            <button
              onClick={() => setShowSettings(s => !s)}
              style={{
                cursor: 'pointer',
                background: showSettings
                  ? 'linear-gradient(135deg, rgba(192,132,252,0.18), rgba(129,140,248,0.1))'
                  : 'rgba(255,255,255,0.04)',
                padding: '0.5rem 1rem',
                fontSize: '0.8rem',
                fontFamily: 'var(--font-display)',
                fontWeight: 600,
                color: 'var(--primary)',
                border: '1px solid rgba(192,132,252,0.25)',
                borderRadius: '8px',
                width: '100%',
                transition: 'all 0.2s ease',
                letterSpacing: '0.5px',
              }}
            >
              {showSettings ? 'Hide Voice Lab' : '🎤 Voice Lab'}
            </button>

            {showSettings && (
              <div style={{ marginTop: '1rem', animation: 'fadeIn 0.3s ease' }}>
                <h3 style={{ margin: '0 0 0.9rem', color: 'var(--primary)', fontSize: '0.85rem',
                              fontFamily: 'var(--font-display)', fontWeight: 700, letterSpacing: 1 }}>
                  Voice Tuner
                </h3>
                {/* Pitch */}
                <div style={{ marginBottom: '1rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem',
                                 marginBottom: '6px', color: 'var(--text-secondary)' }}>
                    <span>Pitch</span>
                    <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--primary)' }}>
                      {voicePitch.toFixed(1)}
                    </span>
                  </div>
                  <input type="range" min="0.5" max="2.0" step="0.1"
                         value={voicePitch}
                         onChange={e => setVoicePitch(parseFloat(e.target.value))} />
                </div>
                {/* Speed */}
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem',
                                 marginBottom: '6px', color: 'var(--text-secondary)' }}>
                    <span>Speed</span>
                    <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--primary)' }}>
                      {voiceRate.toFixed(1)}
                    </span>
                  </div>
                  <input type="range" min="0.5" max="2.0" step="0.1"
                         value={voiceRate}
                         onChange={e => setVoiceRate(parseFloat(e.target.value))} />
                </div>
              </div>
            )}
          </DraggablePanel>
        )}
      </div>

      {/* ── BOTTOM DOCK ───────────────────────────────────────────────────── */}
      <div className="layout-dock">
        <button className={`dock-btn ${showChatPanel        ? 'active' : ''}`} onClick={toggleChatPanel}>Chat</button>
        {voiceEnabled && (
          <button className={`dock-btn ${showVoiceLabPanel   ? 'active' : ''}`} onClick={toggleVoiceLabPanel}>Voice Lab</button>
        )}
        <button className={`dock-btn ${showMoodPanel        ? 'active' : ''}`} onClick={toggleMoodPanel}>Mood</button>
        <button className={`dock-btn ${showUserMoodPanel    ? 'active' : ''}`} onClick={toggleUserMoodPanel}>User</button>
        <button className={`dock-btn ${showStatusPanel      ? 'active' : ''}`} onClick={toggleStatusPanel}>Status</button>
        <button className={`dock-btn ${showBrainMonitor     ? 'active' : ''}`} onClick={toggleBrainMonitor}>Telemetry</button>
        <button className={`dock-btn ${showNewsPanel        ? 'active' : ''}`} onClick={toggleNewsPanel}>News</button>
        <button className={`dock-btn ${showAutonomyPanel    ? 'active' : ''}`} onClick={toggleAutonomyPanel}>Autonomy</button>
        <button className={`dock-btn ${showGovernancePanel  ? 'active' : ''}`} onClick={toggleGovernancePanel}>Governance</button>
        <button className={`dock-btn ${showGevPanel         ? 'active' : ''}`} onClick={toggleGevPanel}>GEV Map</button>
      </div>
    </div>
  );
}
