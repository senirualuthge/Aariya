// Tests for the 3-layer AdvancedMemoryManager (Wave-2 G1): the mid-term
// session log, real topic extraction, emotion trend, and MTM retrieval.
// Runs under `node --test` (localStorage reads are guarded, no browser needed).
import test from 'node:test';
import assert from 'node:assert/strict';

import { AdvancedMemoryManager, MEMORY_TIERS } from './AdvancedMemoryManager.js';

function fresh() {
  const m = new AdvancedMemoryManager();
  clearInterval(m.saveInterval);
  return m;
}

test('MTM keeps the full session log beyond the STM window', () => {
  const m = fresh();
  const total = MEMORY_TIERS.STM_MAX + 5;
  for (let i = 0; i < total; i++) m.addInteraction('user', `message number ${i}`);

  assert.equal(m.stm.buffer.length, MEMORY_TIERS.STM_MAX);
  assert.equal(m.mtm.history.length, total);
});

test('topics are extracted from real interaction text', () => {
  const m = fresh();
  m.addInteraction('user', 'I love quantum physics and quantum computing');

  const topics = m.getTopicSummary(3).map((t) => t.topic);
  assert.ok(topics.includes('quantum'));
  assert.equal(m.getTopicSummary(1)[0].count, 2); // "quantum" appears twice
});

test('emotion trend is derived from real valence signals only', () => {
  const m = fresh();
  m.addInteraction('user', 'a', { valence: 1.0 });
  m.addInteraction('user', 'b', { valence: 1.0 });
  assert.equal(m.mtm.emotionTrend.samples, 2);
  assert.equal(m.mtm.emotionTrend.avgValence, 1.0);
  assert.equal(m.mtm.emotionTrend.volatility, 0.0);

  // A named emotion maps through the documented lexicon…
  m.addInteraction('user', 'c', { emotion: 'sad' });
  assert.equal(m.mtm.emotionTrend.samples, 3);
  assert.ok(m.mtm.emotionTrend.avgValence < 1.0);

  // …but an unknown label contributes nothing (no invention).
  m.addInteraction('user', 'd', { emotion: 'bewildered' });
  assert.equal(m.mtm.emotionTrend.samples, 3);
});

test('retrieveContext ranks a deeper MTM hit and labels its tier', () => {
  const m = fresh();
  m.addInteraction('user', 'tell me about black holes');
  for (let i = 0; i < MEMORY_TIERS.STM_MAX; i++) m.addInteraction('ai', `filler ${i}`);

  const hits = m.retrieveContext('black holes');
  assert.equal(hits.length, 1);
  assert.equal(hits[0].source, 'MTM'); // has aged out of the STM window
  assert.match(hits[0].content, /black holes/);
});

test('retrieveContext labels a recent hit as STM', () => {
  const m = fresh();
  m.addInteraction('user', 'what is entropy exactly');
  const hits = m.retrieveContext('entropy');
  assert.equal(hits.length, 1);
  assert.equal(hits[0].source, 'STM');
});
