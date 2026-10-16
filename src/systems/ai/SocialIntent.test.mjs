// Tests for the social-intent layer (Wave-2 H): the store stance field and the
// deterministic NeuralEngine.resolveSocialIntent rules.
import test from 'node:test';
import assert from 'node:assert/strict';

import useStore from '../../store.js';
import { neuralEngine } from './NeuralEngine.js';

const BASE = { intent: 'LISTENING', warmth: 0.5, dominance: 0.0, openness: 0.5, engagement: 0.5 };

test('store exposes a neutral LISTENING social intent by default', () => {
  const si = useStore.getState().socialIntent;
  assert.equal(si.intent, 'LISTENING');
  assert.ok(si.warmth >= 0 && si.warmth <= 1);
});

test('setSocialIntent replaces the stance', () => {
  useStore.getState().setSocialIntent({ ...BASE, intent: 'TEASING' });
  assert.equal(useStore.getState().socialIntent.intent, 'TEASING');
});

test('resolveSocialIntent applies the documented rules', () => {
  const comfort = neuralEngine.resolveSocialIntent(
    { emotions: { sad: 0.9 }, socialIntent: BASE, arousal: 0.2 }, 1,
  );
  assert.equal(comfort.intent, 'COMFORTING');
  assert.ok(comfort.warmth > BASE.warmth);

  const boundary = neuralEngine.resolveSocialIntent(
    { emotions: { angry: 0.8 }, socialIntent: BASE, arousal: 0.5 }, 1,
  );
  assert.equal(boundary.intent, 'SETTING_BOUNDARY');

  // TEASING needs happy + arousal; arousal comes from the store root.
  const tease = neuralEngine.resolveSocialIntent(
    { emotions: { happy: 0.9 }, socialIntent: BASE, arousal: 0.8 }, 1,
  );
  assert.equal(tease.intent, 'TEASING');

  const listen = neuralEngine.resolveSocialIntent(
    { emotions: { happy: 0.1 }, socialIntent: BASE, arousal: 0.1 }, 1,
  );
  assert.equal(listen.intent, 'LISTENING');
});

test('resolveSocialIntent returns bounded axes', () => {
  const out = neuralEngine.resolveSocialIntent(
    { emotions: { sad: 1, angry: 1, happy: 1 }, socialIntent: base(), arousal: 1 }, 5,
  );
  for (const key of ['warmth', 'dominance', 'openness', 'engagement']) {
    assert.ok(out[key] >= 0 && out[key] <= 1, `${key} in [0,1]`);
  }
});

function base() {
  return { intent: 'LISTENING', warmth: 0.5, dominance: 0.0, openness: 0.5, engagement: 0.5 };
}
