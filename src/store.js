import { create } from 'zustand';
import { apiBase } from './utils/apiHost';

// ── Autonomy live-strip persistence ──────────────────────────────────────────
// The daemon's real activity (latest proactive action, plan lifecycle status,
// rolling event ring) is saved to localStorage so the Mind panel's live strip
// shows what happened while the tab / panel was closed. The daemon only
// broadcasts NEW events on reconnect, so without persistence the strip would
// start blank after every reload. Wrapped in try/catch: storage can be
// unavailable (private mode, disabled) — the strip simply starts empty.
const AUTONOMY_STRIP_KEY = 'AIGirl_autonomy_strip';

function loadAutonomyStrip() {
  try {
    const raw = localStorage.getItem(AUTONOMY_STRIP_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    const now = Date.now() / 1000;
    return {
      lastProactive: parsed.lastProactive || null,
      planStatus: parsed.planStatus || null,
      activity: Array.isArray(parsed.activity) ? parsed.activity.slice(0, 8) : [],
      rate: Array.isArray(parsed.rate)
        ? parsed.rate
            .filter((b) => b && Number.isFinite(b.t) && b.t > now - RATE_WINDOW_SECONDS)
            .slice(-60)
        : [],
    };
  } catch {
    return null;
  }
}

// Long texts (e.g. stream_of_consciousness) are trimmed on persist so the key
// can't grow unbounded; the in-memory ring keeps the full text for this session.
function _trimForStorage(entry) {
  if (!entry || typeof entry !== 'object') return entry;
  const out = { ...entry };
  for (const k of ['text', 'content', 'title']) {
    if (typeof out[k] === 'string' && out[k].length > 300) out[k] = `${out[k].slice(0, 300)}…`;
  }
  return out;
}

function persistAutonomyStrip(autonomy) {
  try {
    const now = Date.now() / 1000;
    localStorage.setItem(AUTONOMY_STRIP_KEY, JSON.stringify({
      lastProactive: _trimForStorage(autonomy.lastProactive) || null,
      planStatus: autonomy.planStatus || null,
      activity: (autonomy.activity || []).slice(0, 8).map(_trimForStorage),
      rate: (autonomy.rate || [])
        .filter((b) => b && Number.isFinite(b.t) && b.t > now - RATE_WINDOW_SECONDS)
        .slice(-60),
    }));
  } catch {
    /* storage unavailable — strip just won't persist */
  }
}

// ── Activity rate (sparkline data) ─────────────────────────────────────────
// Real daemon events bucketed per minute, kept for the last hour. Buckets are
// appended in time order; a new event in the same minute just increments the
// current bucket. Old buckets age out on the next event / persist / load.
const RATE_BUCKET_SECONDS = 60;
const RATE_WINDOW_SECONDS = 3600;

// ts is an event timestamp in epoch SECONDS (as the daemon frames carry);
// bucketing math assumes seconds, so callers must not pass milliseconds.
function bumpActivityRate(rate, ts) {
  const now = Date.now() / 1000;
  const t = Number.isFinite(ts) ? ts : now;
  const bucketStart = Math.floor(t / RATE_BUCKET_SECONDS) * RATE_BUCKET_SECONDS;
  // Events older than the window don't count toward the last hour at all.
  if (bucketStart <= now - RATE_WINDOW_SECONDS) return rate || [];
  const prev = (rate || []).filter((b) => b && b.t > now - RATE_WINDOW_SECONDS);
  // Insert in sorted (newest-first) position: an out-of-order timestamp (e.g.
  // a lagging server clock on plan.ack) must not land at the wrong end of the
  // ring, which would corrupt the same-minute merge and slice(-60) persistence.
  // The first bucket with t <= bucketStart is where this one belongs (all
  // earlier buckets are newer); if none, this bucket is the oldest → append.
  const idx = prev.findIndex((b) => b.t <= bucketStart);
  if (idx === -1) return [...prev, { t: bucketStart, c: 1 }]; // oldest yet
  if (prev[idx].t === bucketStart) {
    prev[idx] = { t: bucketStart, c: prev[idx].c + 1 };
    return prev;
  }
  prev.splice(idx, 0, { t: bucketStart, c: 1 });
  return prev;
}

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

  // ── Person identity (ToDo §4) ──────────────────────────────────────────────────
  // knownPeople: enrolled profiles (descriptor omitted from UI state on purpose —
  //   the panel only needs the human-readable fields). activePerson: whichever
  //   person is currently on camera, or the pending stranger awaiting a name.
  //   identityEnabled: false until the recognition weights load, so the panel can
  //   explain itself instead of appearing broken.
  knownPeople: [],
  activePerson: null,
  identityEnabled: false,
  identityUnavailableReason: null,
  personPanelOpen: false,
  pendingEnrollment: null,
  peopleContext: null,

  setKnownPeople: (people) => set({ knownPeople: people || [] }),
  setActivePerson: (person) => set({ activePerson: person }),
  setIdentityEnabled: (v) => set({ identityEnabled: !!v }),
  setIdentityUnavailable: (reason) =>
    set({ identityUnavailableReason: reason || null, identityEnabled: false }),
  setPersonPanelOpen: (v) => set({ personPanelOpen: !!v }),
  setPendingEnrollment: (pending) => set({ pendingEnrollment: pending }),
  setPeopleContext: (context) => set({ peopleContext: context }),

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
  valence:           0.0,
  arousal:           0.0,
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

  // ── Planetary cognition / synoptic observability (from backend) ────────────
  synoptic:  {},   // { dominant_domain, coherence, conflict, domains }
  planetary: [],   // [{ id, name, radius, orbit_speed, glow, ... }]

  setSynoptic:  (s) => set({ synoptic: s }),
  setPlanetary: (p) => set({ planetary: p }),

  // ── Brain state (from backend) ──────────────────────────────────────────────
  updateState: (brainState) =>
    set({
      trust:              brainState.trust ?? 0.5,
      valence:            brainState.valence ?? 0.0,
      arousal:            brainState.arousal ?? 0.0,
      personalityPreset:  brainState.current_mode ?? 'balanced',
      currentPersonality: brainState.current_mode ?? 'balanced',
      synoptic:           brainState.synoptic ?? {},
      planetary:          brainState.planetary ?? [],
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
    // ── Live strip (latest daemon actions, beyond the chat log) ───────────
    // lastProactive: the most recent real proactive_message from the daemon.
    // planStatus: current plan lifecycle state (awaiting/running/completed/…).
    // activity: rolling ring of recent daemon events for the live strip feed.
    // These three are rehydrated from localStorage so past activity survives
    // reloads (the daemon only broadcasts new events).
    lastProactive: null,   // { content, trigger, urgency, timestamp }
    planStatus: null,      // { plan_id, goal, status, risk_level }
    activity: [],          // [{ kind, title, text, severity, timestamp }]
    rate: [],              // [{ t, c }] real events per 60s bucket (last hour)
    // Persisted snapshot (spread last so it wins over the defaults above;
    // {...null} is a no-op when storage was unavailable).
    ...loadAutonomyStrip(),
  },
  wsSender: null,   // registered by VoiceSystem — sends control commands

  setAutonomyState: (state) =>
    set((prev) => ({ autonomy: { ...prev.autonomy, ...state } })),

  // Prepend a real daemon event to the live-activity ring (newest first,
  // capped) and bump the per-minute activity rate feeding the strip's
  // sparkline. This action is the single funnel for every real daemon event
  // (proactive, plan, thought, model), so the rate counts events, not views.
  pushAutonomyActivity: (entry) =>
    set((prev) => {
      const autonomy = {
        ...prev.autonomy,
        activity: [entry, ...(prev.autonomy.activity || [])].slice(0, 8),
        rate: bumpActivityRate(prev.autonomy.rate, entry && entry.timestamp),
      };
      persistAutonomyStrip(autonomy);
      return { autonomy };
    }),

  // The most recent proactive message the daemon actually sent.
  setLastProactive: (entry) =>
    set((prev) => {
      const autonomy = { ...prev.autonomy, lastProactive: entry };
      persistAutonomyStrip(autonomy);
      return { autonomy };
    }),

  // Current plan lifecycle status (awaiting_approval / running / completed / …).
  setPlanStatus: (entry) =>
    set((prev) => {
      const autonomy = { ...prev.autonomy, planStatus: entry };
      persistAutonomyStrip(autonomy);
      return { autonomy };
    }),

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
      const base = apiBase();
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

  // ── Panel Toggles ───────────────────────────────────────────────────────────
  showChatPanel: true,
  showMoodPanel: true,
  showUserMoodPanel: true,
  showStatusPanel: true,
  showVoiceLabPanel: false,
  showBrainMonitor: true,
  showNewsPanel: true,
  showAutonomyPanel: true,
  showGovernancePanel: true,
  showGevPanel: false,
  gevFocus: null,

  toggleChatPanel: () => set((state) => ({ showChatPanel: !state.showChatPanel })),
  toggleMoodPanel: () => set((state) => ({ showMoodPanel: !state.showMoodPanel })),
  toggleUserMoodPanel: () => set((state) => ({ showUserMoodPanel: !state.showUserMoodPanel })),
  toggleStatusPanel: () => set((state) => ({ showStatusPanel: !state.showStatusPanel })),
  toggleVoiceLabPanel: () => set((state) => ({ showVoiceLabPanel: !state.showVoiceLabPanel })),
  toggleBrainMonitor: () => set((state) => ({ showBrainMonitor: !state.showBrainMonitor })),
  toggleNewsPanel: () => set((state) => ({ showNewsPanel: !state.showNewsPanel })),
  toggleAutonomyPanel: () => set((state) => ({ showAutonomyPanel: !state.showAutonomyPanel })),
  toggleGovernancePanel: () => set((state) => ({ showGovernancePanel: !state.showGovernancePanel })),
  toggleGevPanel: () => set((state) => ({ showGevPanel: !state.showGevPanel })),
  setGevPanel: (val, focus = null) => set({ showGevPanel: val, gevFocus: focus }),
}));

export default useStore;