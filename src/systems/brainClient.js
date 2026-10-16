// src/systems/brainClient.js
//
// Bidirectional client for the backend brain (BrainV2 over /ws/dashboard/stream).
//
// The chat now talks to Aariya's actual cognition — memory, identity, emotion,
// personality, inner monologue — instead of a browser-side OpenAI call. The
// WebSocket is owned by VoiceSystem; this module subscribes to its messages and
// correlates requests → responses with a FIFO queue (the backend replies to the
// same socket, in order).
import { eventBus } from '../core/EventBus';
import useStore from '../store';

// Event names published on the shared event bus
export const BRAIN_EVENT = 'brain:message';            // every server message
export const BRAIN_THOUGHT_EVENT = 'brain:inner_thought'; // private thoughts / idle musings
export const BRAIN_RAG_EVENT = 'brain:rag';            // RAG pipeline telemetry

// FIFO of in-flight chat requests
const pending = [];

function handleServerMessage(data) {
  if (!data || typeof data !== 'object') return;
  eventBus.publish(BRAIN_EVENT, data);

  switch (data.type) {
    case 'text.stream': {
      // Streamed token(s) of the reply currently being generated
      const req = pending[0];
      if (req) {
        req.streamed = (req.streamed || '') + (data.chunk || '');
        if (req.onChunk) req.onChunk(req.streamed, data.chunk);
      }
      break;
    }
    case 'ai_response': {
      // Final complete reply — resolves the oldest pending request
      const req = pending.shift();
      // B4: the backend labels which diarized speaker the reply is addressed to.
      // Only act when the field is present so older servers don't clobber it.
      if ('target_speaker_id' in data) {
        const sid = data.target_speaker_id;
        useStore.getState().setReplyTarget(
          sid == null ? null : {
            speakerId: sid,
            slot: data.target_speaker_slot ?? null,
            count: data.speaker_count ?? 0,
          }
        );
      }
      if (req) {
        clearTimeout(req.timer);
        req.resolve({
          text: data.text,
          streamed: req.streamed || data.text,
          expression: data.expression,
          thought: data.thought,
          targetSpeakerId: data.target_speaker_id ?? null,
        });
      }
      // RAG pipeline telemetry rides on the same reply (meta.rag) — no need
      // for a second socket.
      if (data.meta && data.meta.rag) {
        eventBus.publish(BRAIN_RAG_EVENT, data.meta.rag);
      }
      if (data.meta && data.meta.gev_intent) {
        useStore.getState().setGevPanel(true, data.meta.gev_focus || null);
      }
      break;
    }
    case 'inner_thought':
    case 'stream_of_consciousness': {
      // Visible inner life — her private thinking and idle musings
      if (data.thought) eventBus.publish(BRAIN_THOUGHT_EVENT, data.thought);
      break;
    }
    case 'ambient.suppressed': {
      // Meeting Mode observed ambient speech that wasn't addressed to Aariya —
      // resolve the pending turn as "no reply" instead of letting it time out.
      const req = pending.shift();
      // No reply → nothing is addressed to anyone.
      useStore.getState().setReplyTarget(null);
      if (req) {
        clearTimeout(req.timer);
        req.resolve({ text: '', streamed: '', suppressed: true, reason: data.reason });
      }
      break;
    }
    default:
      break;
  }
}

// How long send() waits for the WebSocket to come up (VoiceSystem registers
// wsSender in the socket's onopen). Submitting before the socket opens used to
// reject instantly, silently falling back to the browser-side generator and
// never reaching the brain — so allow a short grace window first.
const CONNECT_GRACE_MS = 4000;

/**
 * Resolves with the current wsSender, waiting (bounded) for the socket to
 * come up if it isn't registered yet. Rejects when no sender appears in time.
 */
function waitForSender(timeoutMs = CONNECT_GRACE_MS) {
  return new Promise((resolve, reject) => {
    const sender = useStore.getState().wsSender;
    if (sender) return resolve(sender);

    let unsub = () => {};
    const timer = setTimeout(() => {
      unsub();
      reject(new Error('Brain connection not ready'));
    }, timeoutMs);

    // Poll the store — zustand subscribes fire on every state change, which is
    // fine here since we only care about the sender slot becoming non-null.
    unsub = useStore.subscribe((state) => {
      if (state.wsSender) {
        clearTimeout(timer);
        unsub();
        resolve(state.wsSender);
      }
    });
  });
}

/**
 * Send a user message to the backend brain and await the reply.
 * @param {string} text       user message
 * @param {object} opts       { onChunk(streamedText, lastToken), timeoutMs }
 * @returns {Promise<{text, streamed, expression, thought}>}
 */
async function send(text, opts = {}) {
  const sender = await waitForSender();
  return new Promise((resolve, reject) => {
    const req = { resolve, reject, streamed: null, onChunk: opts.onChunk || null };
    req.timer = setTimeout(() => {
      const idx = pending.indexOf(req);
      if (idx >= 0) pending.splice(idx, 1);
      reject(new Error('Brain response timeout'));
    }, opts.timeoutMs || 45000);
    pending.push(req);

    const payload = { type: 'input', text };

    // Track B: carry the real acoustic signals captured by useAudioAnalyzer so
    // Meeting Mode can run its webrtcvad + diarization path and gate ambient
    // chatter. `audio_energy` is normalised to [0,1]; the PCM snapshot (when
    // present) drives the real VAD.
    const state = useStore.getState();
    const stats = state.userAudioStats || {};
    if (typeof stats.energy === 'number') {
      payload.audio_energy = Math.max(0, Math.min(1, stats.energy / 255));
    }
    if (typeof state.userSpeaking === 'boolean') {
      payload.vad_active = state.userSpeaking;
    }
    if (stats.pcm16b64) {
      payload.meeting_pcm_b64 = stats.pcm16b64;
      payload.meeting_sample_rate = stats.pcmSampleRate || 16000;
    }

    sender(payload);
  });
}

export const brainClient = { send, handleServerMessage };
