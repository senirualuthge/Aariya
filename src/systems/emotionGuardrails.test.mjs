// Tests for the shared emotion stability guardrails (Wave-2 G2).
// Runs under `node --test` — the module is pure (no DOM/store required).
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  clampEmotions,
  countSignFlips,
  EmotionGuardrail,
  EMOTION_BASELINE,
} from './emotionGuardrails.js';

test('clampEmotions clamps out-of-range values and rescues non-finite ones', () => {
  const { emotions, changed } = clampEmotions({
    happy: 1.7, calm: -0.3, sad: NaN, angry: undefined, focused: 0.4,
  });
  assert.equal(changed, true);
  assert.equal(emotions.happy, 1);
  assert.equal(emotions.calm, 0);
  assert.equal(emotions.sad, EMOTION_BASELINE.sad);
  assert.equal(emotions.angry, EMOTION_BASELINE.angry);
  assert.equal(emotions.focused, 0.4);
});

test('clampEmotions reports no change for an already-valid vector', () => {
  const valid = { happy: 0.5, calm: 0.5, excited: 0, sad: 0, angry: 0, focused: 0.3 };
  const { changed, emotions } = clampEmotions(valid);
  assert.equal(changed, false);
  assert.deepEqual(emotions, valid);
});

test('countSignFlips distinguishes flat, monotonic and oscillating series', () => {
  assert.equal(countSignFlips([1, 1, 1, 1]), 0);
  assert.equal(countSignFlips([0, 1, 2, 3, 4]), 0);
  assert.ok(countSignFlips([0, 1, 0, 1, 0, 1, 0]) >= 5);
});

test('EmotionGuardrail damps an oscillating axis toward its baseline', () => {
  const g = new EmotionGuardrail({ windowMs: 10000, flipThreshold: 4, damping: 0.5 });
  let now = 0;
  let last;
  let raw = 0;
  for (let i = 0; i < 8; i++) {
    raw = i % 2 ? 1 : 0; // ping-pong around the 0.5 baseline
    last = g.process({ happy: raw, calm: 0.5 }, (now += 100));
  }
  assert.equal(last.oscillationDetected, true);
  // the value was pulled toward the baseline, not left raw
  assert.ok(
    Math.abs(last.emotions.happy - EMOTION_BASELINE.happy) < Math.abs(raw - EMOTION_BASELINE.happy),
  );
});

test('EmotionGuardrail leaves a stable vector untouched', () => {
  const g = new EmotionGuardrail();
  let now = 0;
  let last;
  for (let i = 0; i < 10; i++) {
    last = g.process({ happy: 0.5, calm: 0.5 }, (now += 100));
  }
  assert.equal(last.oscillationDetected, false);
  assert.equal(last.changed, false);
  assert.deepEqual(last.emotions, { happy: 0.5, calm: 0.5 });
});

test('EmotionGuardrail forgets samples outside the window', () => {
  const g = new EmotionGuardrail({ windowMs: 500, flipThreshold: 4 });
  let now = 0;
  let last;
  for (let i = 0; i < 8; i++) {
    last = g.process({ happy: i % 2 ? 1 : 0 }, (now += 1000)); // 1s apart > 500ms window
  }
  // each tick prunes the previous sample, so there is never enough history to
  // register oscillation.
  assert.equal(last.oscillationDetected, false);
});
