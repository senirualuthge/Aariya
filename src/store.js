import { create } from 'zustand';

const useStore = create((set) => ({
  // ── Core lifecycle ──────────────────────────────────────────────────────────
  started:   true,
  thinking:  false,
  speaking:  false,
  listening: false,
  tracking:  false,

  setStarted:   (started)   => set({ started }),
  setThinking:  (thinking)  => set({ thinking }),
  setSpeaking:  (speaking)  => set({ speaking }),
  setListening: (listening) => set({ listening }),
  setTracking:  (tracking)  => set({ tracking }),

  videoRef: null,
  setVideoRef:  (ref)       => set({ videoRef: ref }),

  // ── Voice / Speech ──────────────────────────────────────────────────────────
  voicePitch:    1.0,
  voiceRate:     1.0,
  transcript:    '',
  manualInput:   '',

  setVoicePitch:  (v) => set({ voicePitch: v }),
  setVoiceRate:   (v) => set({ voiceRate: v }),
  setTranscript:  (v) => set({ transcript: v }),
  setManualInput: (v) => set({ manualInput: v }),

  // ── Chat ────────────────────────────────────────────────────────────────────
  chatHistory: [],
  messages:    [],

  addMessage: (role, text) =>
    set((state) => ({ chatHistory: [...state.chatHistory, { role, text }] })),

  setMessages: (updater) =>
    set((state) => ({
      chatHistory: typeof updater === 'function' ? updater(state.chatHistory) : updater,
    })),

  submitText: (text) => {
    if (!text.trim()) return;
    set((state) => ({
      chatHistory: [...state.chatHistory, { role: 'user', text }],
      manualInput: text,
    }));
  },

  addLog: (role, text) =>
    set((state) => ({ chatHistory: [...state.chatHistory, { role, text }] })),

  // Aariya's private thought — visible inner life in the chat stream
  addThought: (text) =>
    set((state) => ({ chatHistory: [...state.chatHistory, { role: 'thought', text, ts: Date.now() }] })),

  clearInputs: () => set({ transcript: '', manualInput: '' }),

  // ── Face / Camera ───────────────────────────────────────────────────────────
  faceDetected: false,
  faceLastSeen: 0,
  userEmotion:  { primary: 'neutral', valence: 0, arousal: 0 },
  userMood:     'neutral',

  setFaceDetected: (v) => set({ faceDetected: v }),
  setFaceLastSeen: (t) => set({ faceLastSeen: t }),
  setUserEmotion:  (e) => set({ userEmotion: e }),
  setUserMood:     (m) => set({ userMood: m }),

  // ── AI Emotions (Aariya's state) ────────────────────────────────────────────
  emotions: {
    happy:   0.5,
    calm:    0.5,
    excited: 0.0,
    sad:     0.0,
    angry:   0.0,
    focused: 0.3,
  },
  aiMood: 'calm',

  setEmotionIntensity: (emotion, value) =>
    set((state) => ({ emotions: { ...state.emotions, [emotion]: value } })),

  setAllEmotions: (emotions) => set({ emotions }),
  setAiMood:      (m) => set({ aiMood: m }),

  // ── Personality ─────────────────────────────────────────────────────────────
  personalityPreset:  'balanced',
  autoPersonality:    true,
  currentPersonality: 'balanced',
  personality: {
    warmth:       0.6,
    energy:       0.5,
    assertiveness: 0.4,
    formality:    0.3,
  },
  personalityAxes: {},

  setPersonalityPreset: (preset) =>
    set({ personalityPreset: preset, currentPersonality: preset }),
  setAutoPersonality:   (auto) => set({ autoPersonality: auto }),
  setPersonality:       (p)    => set({ personality: p }),
  setPersonalityAxes:   (axes) => set({ personalityAxes: axes }),

  // ── Trust / Relationship ────────────────────────────────────────────────────
  trust:             0.5,
  relationshipLevel: 0,
  conversationContext: {
    userName: 'Player',
    lastInteraction: null,
    relationshipLevel: 0,
  },

  setTrust:            (v) => set({ trust: v }),
  increaseRelationship: (delta = 1) =>
    set((state) => ({
      relationshipLevel: state.relationshipLevel + delta,
      conversationContext: {
        ...state.conversationContext,
        relationshipLevel: state.conversationContext.relationshipLevel + delta,
      },
    })),
  setUserName: (name) =>
    set((state) => ({
      conversationContext: { ...state.conversationContext, userName: name },
    })),

  // ── User Audio ──────────────────────────────────────────────────────────────
  userSpeaking:    false,
  userVolume:      0,
  userAudioStats:  { energy: 0, highFreqRatio: 0, isLoud: false },

  setUserSpeaking: (v)    => set({ userSpeaking: v }),
  setUserVolume:   (v)    => set({ userVolume: v }),
  setUserAudioStats: (s)  => set({ userAudioStats: s }),

  // ── Signals (analytics) ─────────────────────────────────────────────────────
  signals: [],

  addSignal: (signal) =>
    set((state) => ({ signals: [signal, ...state.signals].slice(0, 100) })),

  clearSignals: () => set({ signals: [] }),

  // ── Brain state (from backend) ──────────────────────────────────────────────
  updateState: (brainState) =>
    set({
      trust:             brainState.trust ?? 0.5,
      personalityPreset: brainState.current_mode ?? 'balanced',
      currentPersonality: brainState.current_mode ?? 'balanced',
    }),

  // ── Autonomy / Proactivity (Aariya's inner world) ───────────────────────────
  autonomy: {
    enabled: true,
    is_running: false,
    activeGoal: null,
    plans: [],
    initiatives: [],
    insights: [],
    gaps: [],
    actions: [],
  },
  wsSender: null,   // registered by VoiceSystem — sends control commands

  setAutonomyState: (state) =>
    set((prev) => ({ autonomy: { ...prev.autonomy, ...state } })),

  // Add a proactive (unprompted) Aariya message to the chat stream
  addProactiveMessage: (text, meta = {}) =>
    set((state) => ({
      chatHistory: [...state.chatHistory, {
        role: 'bot',
        text,
        proactive: true,
        trigger: meta.trigger || 'initiative',
        ts: meta.timestamp || Date.now(),
      }],
    })),

  registerSender: (fn) => set({ wsSender: fn }),

  sendCommand: (action, payload = {}) => {
    const sender = useStore.getState().wsSender;
    if (sender) {
      sender({ type: 'command', action, ...payload });
    } else {
      // Fallback: REST API when WebSocket is not registered yet
      const base = `http://${window.location.hostname || 'localhost'}:8000`;
      if (action === 'approve_plan') {
        fetch(`${base}/api/autonomy/plans/${payload.plan_id}/approve`, { method: 'POST' });
      } else if (action === 'reject_plan') {
        fetch(`${base}/api/autonomy/plans/${payload.plan_id}/reject`, { method: 'POST' });
      } else if (action === 'autonomy_enabled') {
        fetch(`${base}/api/autonomy/enable`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: payload.enabled }),
        });
      }
    }
  },

  approvePlan: (planId) =>
    useStore.getState().sendCommand('approve_plan', { plan_id: planId }),
  rejectPlan: (planId) =>
    useStore.getState().sendCommand('reject_plan', { plan_id: planId }),
  toggleAutonomy: () => {
    const enabled = !useStore.getState().autonomy.enabled;
    useStore.getState().sendCommand('autonomy_enabled', { enabled });
    set((prev) => ({ autonomy: { ...prev.autonomy, enabled } }));
  },

  // Tell the 24/7 daemon the user is actually here (chat is local, so it
  // would otherwise think you've been silent forever and spam check-ins)
  notifyUserActivity: () => {
    const sender = useStore.getState().wsSender;
    if (sender) sender({ type: 'user_activity' });
  },
}));

export default useStore;