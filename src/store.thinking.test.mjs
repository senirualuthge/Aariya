// Tests for the latency-masking "thinking" state machine (Track F).
// Runs under `node --test` — the store is imported headless (its localStorage
// reads are guarded, so no browser is required).
import test from 'node:test';
import assert from 'node:assert/strict';

import useStore, { THINKING_MIN_VISIBLE_MS, _resetThinkingForTests } from './store.js';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

test('setThinking(true) shows the affordance immediately', () => {
  _resetThinkingForTests();
  assert.equal(useStore.getState().thinkingVisible, false);

  useStore.getState().setThinking(true);
  const s = useStore.getState();
  assert.equal(s.thinking, true);
  assert.equal(s.thinkingVisible, true);
  assert.ok(typeof s.thinkingSince === 'number');
});

test('raw flag clears at once, display is held for the floor', async () => {
  _resetThinkingForTests();
  useStore.getState().setThinking(true);
  useStore.getState().setThinking(false);

  // the raw flag collapses immediately…
  assert.equal(useStore.getState().thinking, false);
  // …but the affordance is still on-screen.
  assert.equal(useStore.getState().thinkingVisible, true);

  await sleep(THINKING_MIN_VISIBLE_MS + 120);
  assert.equal(useStore.getState().thinkingVisible, false);
});

test('a long think hides immediately when it ends', async () => {
  _resetThinkingForTests();
  useStore.getState().setThinking(true);
  await sleep(THINKING_MIN_VISIBLE_MS + 120);

  useStore.getState().setThinking(false);
  assert.equal(useStore.getState().thinking, false);
  assert.equal(useStore.getState().thinkingVisible, false, 'floor already elapsed');
});

test('repeated true does not extend the min-hold window', () => {
  _resetThinkingForTests();
  useStore.getState().setThinking(true);
  const first = useStore.getState().thinkingSince;

  useStore.getState().setThinking(true);
  assert.equal(useStore.getState().thinkingSince, first, 'clock is not re-armed while thinking');
});

test('a fresh think during the hold keeps the affordance on', async () => {
  _resetThinkingForTests();
  useStore.getState().setThinking(true);
  useStore.getState().setThinking(false); // arms the hide timer
  useStore.getState().setThinking(true);  // new think cancels the hide

  await sleep(THINKING_MIN_VISIBLE_MS + 120);
  assert.equal(useStore.getState().thinkingVisible, true, 'still thinking');
});
