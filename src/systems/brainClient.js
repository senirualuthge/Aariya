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
      if (req) {
        clearTimeout(req.timer);
        req.resolve({
          text: data.text,
          streamed: req.streamed || data.text,
          expression: data.expression,
          thought: data.thought,
        });
      }
      // RAG pipeline telemetry rides on the same reply (meta.rag) — no need
      // for a second socket.
      if (data.meta && data.meta.rag) {
        eventBus.publish(BRAIN_RAG_EVENT, data.meta.rag);
      }
      break;
    }
    case 'inner_thought':
    case 'stream_of_consciousness': {
      // Visible inner life — her private thinking and idle musings
      if (data.thought) eventBus.publish(BRAIN_THOUGHT_EVENT, data.thought);
      break;
    }
    default:
      break;
  }
}

/**
 * Send a user message to the backend brain and await the reply.
 * @param {string} text       user message
 * @param {object} opts       { onChunk(streamedText, lastToken), timeoutMs }
 * @returns {Promise<{text, streamed, expression, thought}>}
 */
function send(text, opts = {}) {
  const sender = useStore.getState().wsSender;
  if (!sender) {
    return Promise.reject(new Error('Brain connection not ready'));
  }
  return new Promise((resolve, reject) => {
    const req = { resolve, reject, streamed: null, onChunk: opts.onChunk || null };
    req.timer = setTimeout(() => {
      const idx = pending.indexOf(req);
      if (idx >= 0) pending.splice(idx, 1);
      reject(new Error('Brain response timeout'));
    }, opts.timeoutMs || 45000);
    pending.push(req);
    sender({ type: 'input', text });
  });
}

export const brainClient = { send, handleServerMessage };
