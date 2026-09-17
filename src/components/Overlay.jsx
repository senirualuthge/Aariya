import React, { useState, useRef, useEffect } from 'react';
import useStore from '../store';
import DraggablePanel from './DraggablePanel';
import PresenceChip from './PresenceChip';
import GEVPanel from './GEVPanel';
import { apiBase } from '../utils/apiHost';

// Mood bar colors
const moodColors = {
  happy: '#a8e6cf',
  excited: '#ffd93d',
  calm: '#6bcbef',
  neutral: '#b8b8b8',
  confused: '#e8a9f0',
  tired: '#9d8cff',
  stressed: '#ff9a9e',
  sad: '#7eb8da',
  angry: '#ff6b6b',
  focused: '#00d9ff',
  bored: '#8b8b8b',
  anxious: '#ffb347'
};

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
    showGevPanel, toggleGevPanel
  } = useStore();

  const [inputValue, setInputValue] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const chatEndRef = useRef(null);

  // Auto-scroll to bottom
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory]);

  // Fetch system health to determine voice availability
  useEffect(() => {
    fetch(`${apiBase()}/api/system/health`)
      .then(res => res.json())
      .then(data => {
        const checks = Array.isArray(data?.checks) ? data.checks : [];
        const voiceCheck = checks.find(c => c.name === 'voice');
        const status = voiceCheck?.status;
        const meta = voiceCheck?.meta || {};
        const whisperUp = meta.whisper !== false && meta.whisper !== undefined;
        const vadUp = meta.vad !== false && meta.vad !== undefined;
        if (status === 'down' || status === 'unknown' || !whisperUp || !vadUp) {
          setVoiceEnabled(false);
        }
      })
      .catch(err => console.error('Failed to fetch system health:', err));
  }, []);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!inputValue.trim()) return;
    submitText(inputValue);
    setInputValue("");
  };

  const defaultEmotion = { valence: 0, arousal: 0, primary: 'neutral' };
  const safeEmotion = userEmotion || defaultEmotion;
  const computedValence = isNaN(safeEmotion.valence) ? 0 : Math.max(-1, Math.min(1, safeEmotion.valence));
  const computedArousal = isNaN(safeEmotion.arousal) ? 0 : Math.max(0, Math.min(1, safeEmotion.arousal));

  const getUserMoods = () => {
    // Calculate derived mood intensities based on valence-arousal model
    const moods = {
      [safeEmotion.primary || 'neutral']: 0.8, // Primary mood always shown
    };
    
    // High arousal + positive valence = excited
    if (computedArousal > 0.5 && computedValence > 0.3) moods.excited = Math.min(computedArousal * computedValence, 1);
    // Low arousal + positive valence = calm
    if (computedArousal < 0.4 && computedValence > 0.2) moods.calm = Math.min((1 - computedArousal) * 0.5, 1);
    // High arousal + negative valence = stressed/anxious
    if (computedArousal > 0.6 && computedValence < -0.2) moods.stressed = Math.min(computedArousal * Math.abs(computedValence), 1);
    // Low arousal + negative valence = tired/sad
    if (computedArousal < 0.3 && computedValence < 0) moods.tired = Math.min((1 - computedArousal) * 0.4, 1);
    // Medium arousal + neutral = focused
    if (computedArousal > 0.3 && computedArousal < 0.7 && Math.abs(computedValence) < 0.3) moods.focused = 0.4;
    
    // Filter out NaN or completely dead states
    Object.keys(moods).forEach(k => { if (isNaN(moods[k])) moods[k] = 0; });
    return moods;
  };

  const userMoods = getUserMoods();

  return (
    <div className="overlay">

      {/* HEADER - Draggable */}
      <DraggablePanel 
        id="aariya_header"
        defaultPosition={{ x: 32, y: 32 }}
        autoHeight={true}
        className="ui-panel"
        style={{ borderLeft: '4px solid #ff8fa3' }}
      >
        <h1 className="drag-handle" style={{ margin: 0, fontSize: '2rem', letterSpacing: '2px', background: 'linear-gradient(90deg, #fff, #ffc0cb)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', cursor: 'grab' }}>
          AARIYA
        </h1>
        <div className="subtitle drag-handle" style={{ color: '#ff8fa3', textTransform: 'uppercase', fontSize: '0.7rem', letterSpacing: '4px', cursor: 'grab' }}>Anime Companion</div>
        {/* Companion presence chip — real mode + trait count from the synoptic,
            visible on the orb home screen without opening chat. */}
        <PresenceChip />
      </DraggablePanel>

      {showGevPanel && <GEVPanel />}

      {/* LEFT SIDE: Chat Panel - Draggable */}
      {showChatPanel && (
      <DraggablePanel
        id="aariya_chat"
        defaultPosition={{ x: 32, y: 128 }}
        defaultSize={{ width: '380px', height: '550px' }}
        className="ui-panel chat-panel"
      >
        {/* Drag Handle */}
        <div className="drag-handle panel-title-bar">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
          Chat Stream
        </div>

        {/* Chat History */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '1.2rem', display: 'flex', flexDirection: 'column', gap: '0.8rem' }} className="scrollbar-hide">
          {chatHistory.length === 0 && (
            <div style={{ textAlign: 'center', color: 'rgba(255,255,255,0.4)', marginTop: '50%', fontStyle: 'italic', fontSize: '0.9rem' }}>
              Say "Hello" or type a message...
            </div>
          )}
          {chatHistory.map((msg, i) => (
            msg.role === 'thought' ? (
              <div key={i} style={{
                alignSelf: 'flex-start',
                maxWidth: '88%',
                fontSize: '0.8rem',
                fontStyle: 'italic',
                color: 'rgba(155, 195, 255, 0.55)',
                padding: '0.3rem 0.4rem 0 0.4rem',
                lineHeight: '1.35',
                animation: 'fadeIn 0.5s ease-out forwards',
                letterSpacing: '0.2px'
              }}>
                <span style={{ opacity: 0.7, marginRight: 6 }}>💭</span>
                {msg.text}
              </div>
            ) : (
            <div key={i} style={{
              alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
              background: msg.role === 'user' ? 'rgba(255, 255, 255, 0.08)' : 'linear-gradient(135deg, rgba(255, 143, 163, 0.15), rgba(255, 179, 193, 0.05))',
              border: msg.role === 'user' ? '1px solid rgba(255,255,255,0.1)' : '1px solid rgba(255, 143, 163, 0.2)',
              boxShadow: msg.role === 'bot' ? '0 4px 15px rgba(255, 143, 163, 0.1)' : 'none',
              padding: '0.8rem 1.2rem',
              borderRadius: '16px',
              borderBottomRightRadius: msg.role === 'user' ? '4px' : '16px',
              borderTopLeftRadius: msg.role === 'bot' ? '4px' : '16px',
              maxWidth: '88%',
              fontSize: '0.95rem',
              color: msg.role === 'user' ? '#ffffff' : '#ffe0e6',
              backdropFilter: 'blur(8px)',
              animation: 'fadeIn 0.3s ease-out forwards',
              lineHeight: '1.4'
            }}>
              <span style={{ 
                fontSize: '0.65rem', 
                opacity: 0.8, 
                display: 'block', 
                marginBottom: '4px', 
                textTransform: 'uppercase',
                letterSpacing: '1px',
                fontWeight: '600',
                color: msg.role === 'bot' ? '#ff8fa3' : '#a8e6cf'
              }}>
                {msg.role === 'user' ? 'You' : msg.proactive ? '💫 Aariya · proactive' : 'Aariya'}
                {msg.streaming && <span style={{ marginLeft: 6, fontWeight: 400, opacity: 0.7 }}>…</span>}
              </span>
              {msg.text}
              {msg.proactive && (
                <span style={{ display: 'block', marginTop: 6, fontSize: '0.6rem', color: 'rgba(0, 242, 255, 0.65)', letterSpacing: '1px', textTransform: 'uppercase' }}>
                  ✦ she reached out on her own
                </span>
              )}
            </div>
            )
          ))}
          <div ref={chatEndRef} />
        </div>

        {/* Input Area */}
        <form onSubmit={handleSubmit} style={{ 
          padding: '1rem', 
          borderTop: '1px solid rgba(255, 143, 163, 0.15)', 
          background: 'rgba(0,0,0,0.3)',
          display: 'flex',
          gap: '8px'
        }}>
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="Type your message..."
            style={{
              flex: 1,
              background: 'rgba(255,255,255,0.05)',
              border: '1px solid rgba(255, 255, 255, 0.1)',
              padding: '0.8rem 1.2rem',
              borderRadius: '24px',
              color: 'white',
              outline: 'none',
              fontFamily: 'inherit',
              transition: 'all 0.3s ease',
              boxShadow: 'inset 0 2px 4px rgba(0,0,0,0.2)'
            }}
            onFocus={(e) => {
              e.target.style.background = 'rgba(255, 255, 255, 0.1)';
              e.target.style.borderColor = 'rgba(255, 143, 163, 0.4)';
              e.target.style.boxShadow = '0 0 15px rgba(255, 143, 163, 0.2)';
            }}
            onBlur={(e) => {
              e.target.style.background = 'rgba(255, 255, 255, 0.05)';
              e.target.style.borderColor = 'rgba(255, 255, 255, 0.1)';
              e.target.style.boxShadow = 'inset 0 2px 4px rgba(0,0,0,0.2)';
            }}
          />
          <button 
            type="submit" 
            style={{
              background: 'linear-gradient(135deg, #ffb3c1, #ff8fa3)',
              border: 'none',
              borderRadius: '50%',
              width: '42px',
              height: '42px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              boxShadow: '0 4px 10px rgba(255, 143, 163, 0.3)',
              transition: 'transform 0.2s, box-shadow 0.2s',
              color: '#1a0b12',
              flexShrink: 0
            }}
            onMouseOver={(e) => {
              e.currentTarget.style.transform = 'scale(1.05)';
              e.currentTarget.style.boxShadow = '0 6px 15px rgba(255, 143, 163, 0.5)';
            }}
            onMouseOut={(e) => {
              e.currentTarget.style.transform = 'scale(1)';
              e.currentTarget.style.boxShadow = '0 4px 10px rgba(255, 143, 163, 0.3)';
            }}
            onMouseDown={(e) => e.currentTarget.style.transform = 'scale(0.95)'}
            onMouseUp={(e) => e.currentTarget.style.transform = 'scale(1.05)'}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ marginLeft: '-2px' }}>
              <line x1="22" y1="2" x2="11" y2="13"></line>
              <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
            </svg>
          </button>
        </form>
      </DraggablePanel>
      )}

      {/* AI Control Center Button (Always visible on top right) */}
      <button 
        className="control-center-btn"
        style={{
          position: 'absolute',
          top: 32,
          right: 32,
          background: 'linear-gradient(135deg, rgba(0, 242, 255, 0.1), rgba(11, 20, 26, 0.8))',
          border: '1px solid rgba(0, 242, 255, 0.5)',
          color: '#00f2ff',
          padding: '0.7rem 1.4rem',
          borderRadius: '4px',
          cursor: 'pointer',
          zIndex: 50,
          backdropFilter: 'blur(20px)',
          fontWeight: 800,
          letterSpacing: '2px',
          textTransform: 'uppercase',
          fontSize: '0.75rem',
          boxShadow: '0 0 15px rgba(0, 242, 255, 0.2), inset 0 0 12px rgba(0, 242, 255, 0.1)',
          transition: 'all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275)',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          pointerEvents: 'auto'
        }}
        onMouseOver={(e) => {
          e.currentTarget.style.background = 'linear-gradient(135deg, rgba(0, 242, 255, 0.25), rgba(11, 20, 26, 0.9))';
          e.currentTarget.style.boxShadow = '0 0 25px rgba(0, 242, 255, 0.5), inset 0 0 15px rgba(0, 242, 255, 0.3)';
          e.currentTarget.style.transform = 'scale(1.05) translateY(-2px)';
          e.currentTarget.style.border = '1px solid rgba(0, 242, 255, 0.8)';
          e.currentTarget.style.color = '#fff';
        }}
        onMouseOut={(e) => {
          e.currentTarget.style.background = 'linear-gradient(135deg, rgba(0, 242, 255, 0.1), rgba(11, 20, 26, 0.8))';
          e.currentTarget.style.boxShadow = '0 0 15px rgba(0, 242, 255, 0.2), inset 0 0 12px rgba(0, 242, 255, 0.1)';
          e.currentTarget.style.transform = 'scale(1) translateY(0)';
          e.currentTarget.style.border = '1px solid rgba(0, 242, 255, 0.5)';
          e.currentTarget.style.color = '#00f2ff';
        }}
        onMouseDown={(e) => e.currentTarget.style.transform = 'scale(0.95)'}
        onClick={() => {
          console.log('[Overlay] AI Control Center clicked');
          if (window.electronAPI && window.electronAPI.openAnalytics) {
            console.log('[Overlay] Calling electronAPI.openAnalytics()');
            window.electronAPI.openAnalytics();
          } else {
            console.log('[Overlay] No electronAPI found, falling back to window.open');
            // Browser fallback — open in new tab with query param
            window.open('http://localhost:5173/?route=analytics', '_blank', 'width=1200,height=800');
          }
        }}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="3"></circle>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
        </svg>
        AI Control Center
      </button>

      {/* RIGHT SIDE: Status & Settings - Always mounted, hidden when not started */}
      <div style={{ visibility: started ? 'visible' : 'hidden', pointerEvents: started ? 'auto' : 'none', position: 'absolute', inset: 0 }}>
          {/* Mood Meter - Draggable */}
          {showMoodPanel && (
          <DraggablePanel
            id="aariya_mood"
            defaultPosition={{ x: window.innerWidth - 270, y: window.innerHeight - 450 }}
            defaultSize={{ width: '220px' }}
            autoHeight={true}
            className="ui-panel"
            style={{ minWidth: '220px' }}
          >
            <div className="drag-handle drag-handle-mini">⋮⋮ Drag</div>
            <h3 style={{ margin: '0 0 0.5rem 0', color: '#ff8fa3', fontSize: '0.9rem' }}>🎭 Aariya's Mood</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
              {Object.entries(emotions).map(([emotion, value]) => {
                if (value < 0.05) return null;
                return (
                  <div key={emotion} style={{ fontSize: '0.75rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '2px', textTransform: 'capitalize' }}>
                      <span>{emotion}</span>
                      <span>{Math.round(value * 100)}%</span>
                    </div>
                    <div style={{ width: '100%', height: '4px', background: 'rgba(255,255,255,0.1)', borderRadius: '2px' }}>
                      <div style={{ 
                        width: `${value * 100}%`, 
                        height: '100%', 
                        background: moodColors[emotion] || '#ff8fa3',
                        borderRadius: '2px',
                        transition: 'width 0.5s ease'
                      }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </DraggablePanel>
          )}

          {/* User Mood Meter - Draggable with More Moods */}
          {showUserMoodPanel && (
          <DraggablePanel
            id="aariya_user_mood"
            defaultPosition={{ x: window.innerWidth - 270, y: window.innerHeight - 280 }}
            defaultSize={{ width: '220px' }}
            autoHeight={true}
            className="ui-panel"
            style={{ minWidth: '220px' }}
          >
            <div className="drag-handle drag-handle-mini">⋮⋮ Drag</div>
            <h3 style={{ margin: '0 0 0.5rem 0', color: '#a8e6cf', fontSize: '0.9rem' }}>👤 Your Mood</h3>
            
            {faceDetected ? (
              <>
                {/* Primary State */}
                <div style={{ fontSize: '0.8rem', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{opacity: 0.7}}>Primary:</span> 
                  <span style={{ 
                    fontWeight: 'bold', 
                    color: moodColors[userEmotion.primary] || 'white',
                    textTransform: 'uppercase',
                    padding: '2px 8px',
                    background: 'rgba(255,255,255,0.1)',
                    borderRadius: '4px'
                  }}>{userEmotion.primary}</span>
                </div>
                
                {/* Mood Bars */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                  {Object.entries(userMoods).map(([mood, value]) => {
                    if (value < 0.1) return null;
                    return (
                      <div key={mood} style={{ fontSize: '0.75rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '2px', textTransform: 'capitalize' }}>
                          <span>{mood}</span>
                          <span>{Math.round(value * 100)}%</span>
                        </div>
                        <div style={{ width: '100%', height: '4px', background: 'rgba(255,255,255,0.1)', borderRadius: '2px' }}>
                          <div style={{ 
                            width: `${value * 100}%`, 
                            height: '100%', 
                            background: moodColors[mood] || '#a8e6cf',
                            borderRadius: '2px',
                            transition: 'width 0.3s ease'
                          }} />
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Valence/Arousal Meters */}
                <div style={{ marginTop: '0.75rem', paddingTop: '0.5rem', borderTop: '1px solid rgba(255,255,255,0.1)' }}>
                  {/* Valence (Positive/Negative) */}
                  <div style={{ fontSize: '0.7rem', marginBottom: '4px', display: 'flex', justifyContent: 'space-between' }}>
                    <span>Valence</span>
                    <span style={{ color: computedValence > 0 ? '#a8e6cf' : computedValence < 0 ? '#ff9a9e' : '#888' }}>
                      {computedValence > 0 ? '😊 Positive' : computedValence < 0 ? '😔 Negative' : '😐 Neutral'} ({Math.round(Math.abs(computedValence) * 100)}%)
                    </span>
                  </div>
                  <div style={{ width: '100%', height: '6px', background: 'rgba(255,255,255,0.1)', borderRadius: '3px', position: 'relative' }}>
                    <div style={{ 
                      position: 'absolute',
                      left: '50%',
                      width: '2px',
                      height: '100%',
                      background: 'rgba(255,255,255,0.3)'
                    }} />
                    <div style={{ 
                      position: 'absolute',
                      left: computedValence >= 0 ? '50%' : `${50 + (computedValence * 50)}%`,
                      width: `${Math.abs(computedValence) * 50}%`, 
                      height: '100%', 
                      background: computedValence >= 0 ? '#a8e6cf' : '#ff9a9e',
                      borderRadius: '3px',
                      transition: 'all 0.3s ease'
                    }} />
                  </div>

                  {/* Arousal (Energy) */}
                  <div style={{ fontSize: '0.7rem', marginTop: '0.5rem', marginBottom: '4px', display: 'flex', justifyContent: 'space-between' }}>
                    <span>Energy</span>
                    <span style={{ color: `hsl(${120 - (computedArousal * 80)}, 70%, 60%)` }}>
                      {computedArousal > 0.7 ? '⚡ High' : computedArousal > 0.3 ? '✨ Medium' : '😴 Low'} ({Math.round(computedArousal * 100)}%)
                    </span>
                  </div>
                  <div style={{ width: '100%', height: '6px', background: 'rgba(255,255,255,0.1)', borderRadius: '3px' }}>
                    <div style={{ 
                      width: `${computedArousal * 100}%`, 
                      height: '100%', 
                      background: `linear-gradient(90deg, #6bcbef, #ffd93d, #ff9a9e)`,
                      borderRadius: '3px',
                      transition: 'width 0.3s ease'
                    }} />
                  </div>
                </div>
              </>
            ) : (
              <div style={{ 
                textAlign: 'center', 
                padding: '2rem 1rem',
                color: 'rgba(255,255,255,0.3)',
                fontSize: '0.85rem'
              }}>
                <div style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>👁️</div>
                No face detected
              </div>
            )}
          </DraggablePanel>
          )}

          {/* Status Panel - Draggable */}
          {showStatusPanel && (
          <DraggablePanel
            id="aariya_status"
            defaultPosition={{ x: window.innerWidth - 270, y: window.innerHeight - 100 }}
            defaultSize={{ width: '200px' }}
            autoHeight={true}
            className="ui-panel"
          >
            <div className="drag-handle drag-handle-mini">⋮⋮ Drag</div>
            <div style={{ marginBottom: '0.5rem' }}>
              <span className={`status-indicator ${listening ? 'active' : ''}`} />
              <span>{listening ? 'Listening...' : 'Standby'}</span>
            </div>
            <div style={{ marginBottom: '0.5rem' }}>
              <span className={`status-indicator ${speaking ? 'active' : ''}`} style={{ background: speaking ? '#ff8fa3' : '', boxShadow: speaking ? '0 0 10px #ff8fa3' : '' }} />
              <span>{speaking ? 'Speaking...' : 'Silent'}</span>
            </div>

            {thinking && (
              <div style={{ marginBottom: '0.5rem', animation: 'pulse 1s infinite' }}>
                <span className="status-indicator active" style={{ background: '#fff' }} />
                <span>Thinking...</span>
              </div>
            )}

          </DraggablePanel>
          )}

          {/* Voice Lab Button & Panel - Draggable */}
          {voiceEnabled && showVoiceLabPanel && (
          <DraggablePanel
            id="aariya_voicelab"
            defaultPosition={{ x: window.innerWidth - 270, y: 128 }}
            defaultSize={{ width: '220px' }}
            autoHeight={true}
            className="ui-panel"
          >
            <div className="drag-handle drag-handle-mini">⋮⋮ Drag</div>
            <button
              onClick={() => setShowSettings(!showSettings)}
              style={{
                cursor: 'pointer',
                background: showSettings ? 'rgba(255, 143, 163, 0.2)' : 'transparent',
                padding: '0.5rem 1rem',
                fontSize: '0.9rem',
                color: '#ff8fa3',
                border: '1px solid rgba(255, 143, 163, 0.3)',
                borderRadius: '8px',
                width: '100%'
              }}
            >
              {showSettings ? 'Hide Voice Lab' : '🎤 Voice Lab'}
            </button>

            {showSettings && (
              <div style={{ marginTop: '1rem', animation: 'fadeIn 0.3s ease' }}>
                <h3 style={{ margin: '0 0 1rem 0', color: '#ff8fa3', fontSize: '1rem' }}>Voice Tuner</h3>
                <div style={{ marginBottom: '1rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', marginBottom: '4px' }}>
                    <span>Pitch</span>
                    <span>{voicePitch.toFixed(1)}</span>
                  </div>
                  <input
                    type="range"
                    min="0.5"
                    max="2.0"
                    step="0.1"
                    value={voicePitch}
                    onChange={(e) => setVoicePitch(parseFloat(e.target.value))}
                    style={{ width: '100%', accentColor: '#ff8fa3', cursor: 'pointer' }}
                  />
                </div>
                <div style={{ marginBottom: '1rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', marginBottom: '4px' }}>
                    <span>Speed</span>
                    <span>{voiceRate.toFixed(1)}</span>
                  </div>
                  <input
                    type="range"
                    min="0.5"
                    max="2.0"
                    step="0.1"
                    value={voiceRate}
                    onChange={(e) => setVoiceRate(parseFloat(e.target.value))}
                    style={{ width: '100%', accentColor: '#ff8fa3', cursor: 'pointer' }}
                  />
                </div>
              </div>
            )}
          </DraggablePanel>
          )}
      </div>

      {/* Layout Manager Dock */}
      <div className="layout-dock">
        <button className={`dock-btn ${showChatPanel ? 'active' : ''}`} onClick={toggleChatPanel}>Chat</button>
        {voiceEnabled && (
            <button className={`dock-btn ${showVoiceLabPanel ? 'active' : ''}`} onClick={toggleVoiceLabPanel}>Voice Lab</button>
        )}
        <button className={`dock-btn ${showMoodPanel ? 'active' : ''}`} onClick={toggleMoodPanel}>Aariya Mood</button>
        <button className={`dock-btn ${showUserMoodPanel ? 'active' : ''}`} onClick={toggleUserMoodPanel}>User Mood</button>
        <button className={`dock-btn ${showStatusPanel ? 'active' : ''}`} onClick={toggleStatusPanel}>Status</button>
        <button className={`dock-btn ${showBrainMonitor ? 'active' : ''}`} onClick={toggleBrainMonitor}>Telemetry</button>
        <button className={`dock-btn ${showNewsPanel ? 'active' : ''}`} onClick={toggleNewsPanel}>News</button>
        <button className={`dock-btn ${showAutonomyPanel ? 'active' : ''}`} onClick={toggleAutonomyPanel}>Autonomy</button>
        <button className={`dock-btn ${showGovernancePanel ? 'active' : ''}`} onClick={toggleGovernancePanel}>Governance</button>
        <button className={`dock-btn ${showGevPanel ? 'active' : ''}`} onClick={toggleGevPanel}>GEV Map</button>
      </div>
    </div>
  );
}
