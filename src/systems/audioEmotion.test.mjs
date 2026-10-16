// Tests for the pure audio→affect helpers (systems/audioEmotion.js).
// Runs under `node --test` — the module has no browser dependencies.
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  extractAudioFeatures,
  variationFromHistory,
  audioToEmotion,
  dominantAffect,
  fuseUserAffect,
  AUDIO_REFS,
} from './audioEmotion.js';

const N = 128;

/** Spectrum with every bin at `level`. */
const flat = (level) => new Uint8Array(N).fill(level);
/** Spectrum with the first `bins` bins at `level`. */
function lowConcentrated(level, bins) {
  const a = new Uint8Array(N);
  for (let i = 0; i < Math.min(bins, N); i++) a[i] = level;
  return a;
}
/** Spectrum with the last `bins` bins at `level`. */
function highConcentrated(level, bins) {
  const a = new Uint8Array(N);
  for (let i = N - Math.min(bins, N); i < N; i++) a[i] = level;
  return a;
}

// A spectrum whose energy and centroid land on the resting-speech references.
// 65 bins × 60 → energy ≈ 0.12; centroid = ((65-1)/2)/128 = 0.25.
const restingSpectrum = () => lowConcentrated(60, 65);

test('extractAudioFeatures: silence reports zero energy and no pitch', () => {
  const f = extractAudioFeatures(new Uint8Array(N));
  assert.equal(f.energy, 0);
  assert.equal(f.pitch, 0);
});

test('extractAudioFeatures: guard against empty input', () => {
  assert.deepEqual(extractAudioFeatures(new Uint8Array(0)), { energy: 0, pitch: 0 });
  assert.deepEqual(extractAudioFeatures(null), { energy: 0, pitch: 0 });
});

test('extractAudioFeatures: energy tracks overall level', () => {
  const quiet = extractAudioFeatures(flat(20));
  const loud = extractAudioFeatures(flat(200));
  assert.ok(loud.energy > quiet.energy);
  assert.ok(Math.abs(quiet.energy - 20 / 255) < 1e-6);
  assert.ok(Math.abs(loud.energy - 200 / 255) < 1e-6);
});

test('extractAudioFeatures: pitch is a rising function of brightness', () => {
  const dark = extractAudioFeatures(lowConcentrated(200, 8));
  const bright = extractAudioFeatures(highConcentrated(200, 8));
  assert.ok(bright.pitch > dark.pitch);
});

test('variationFromHistory: flat / short histories read as zero', () => {
  assert.equal(variationFromHistory([]), 0);
  assert.equal(variationFromHistory([0.2]), 0);
  assert.equal(variationFromHistory([0.2, 0.2, 0.2, 0.2]), 0);
  assert.equal(variationFromHistory(null), 0);
});

test('variationFromHistory: change raises the reading and stays bounded', () => {
  const steady = variationFromHistory([0.1, 0.1, 0.1, 0.1]);
  const moving = variationFromHistory([0, 0.5, 0, 0.5, 0, 0.5]);
  assert.ok(moving > steady);
  assert.ok(moving > 0 && moving <= 1);
});

test('audioToEmotion: resting speech reads as ~neutral with real confidence', () => {
  const { energy, pitch } = extractAudioFeatures(restingSpectrum());
  const e = audioToEmotion({ energy, pitch, tempo: 0 });
  assert.ok(Math.abs(e.valence) < 0.05, `valence near 0, got ${e.valence}`);
  assert.ok(e.arousal < 0.05, `arousal near 0, got ${e.arousal}`);
  assert.ok(e.confidence > 0.3, 'resting speech still carries signal');
});

test('audioToEmotion: silence yields zero confidence (no invented affect)', () => {
  const e = audioToEmotion({ energy: 0, pitch: 0, tempo: 0 });
  assert.equal(e.confidence, 0);
});

test('audioToEmotion: bright + loud reads positive valence and high arousal', () => {
  const { energy, pitch } = extractAudioFeatures(flat(255));
  const e = audioToEmotion({ energy, pitch, tempo: 1 });
  assert.ok(e.valence > 0.5, `expected positive valence, got ${e.valence}`);
  assert.ok(e.arousal > 0.6, `expected high arousal, got ${e.arousal}`);
});

test('audioToEmotion: dark + quiet reads negative valence and low arousal', () => {
  const { energy, pitch } = extractAudioFeatures(lowConcentrated(255, 1));
  const e = audioToEmotion({ energy, pitch, tempo: 0 });
  assert.ok(e.valence < -0.5, `expected negative valence, got ${e.valence}`);
  assert.ok(e.arousal < 0.2, `expected low arousal, got ${e.arousal}`);
});

test('audioToEmotion: outputs are always within range', () => {
  for (const args of [
    { energy: 999, pitch: 999, tempo: 999 },
    { energy: -5, pitch: -5, tempo: -5 },
    { energy: NaN, pitch: undefined, tempo: null },
  ]) {
    const e = audioToEmotion(args);
    assert.ok(e.valence >= -1 && e.valence <= 1);
    assert.ok(e.arousal >= 0 && e.arousal <= 1);
    assert.ok(e.confidence >= 0 && e.confidence <= 1);
  }
});

test('dominantAffect: maps the valence/arousal plane to palette labels', () => {
  assert.equal(dominantAffect(0.5, 0.8), 'excited');
  assert.equal(dominantAffect(0.5, 0.4), 'happy');
  assert.equal(dominantAffect(0.5, 0.1), 'calm');
  assert.equal(dominantAffect(0, 0.5), 'neutral');
  assert.equal(dominantAffect(0, 0), 'neutral');
  assert.equal(dominantAffect(-0.5, 0.4), 'angry');
  assert.equal(dominantAffect(-0.5, 0.8), 'stressed');
  assert.equal(dominantAffect(-0.5, 0.1), 'tired');
});

test('dominantAffect: clamps out-of-range inputs', () => {
  assert.equal(dominantAffect(9, 9), 'excited');
  assert.equal(dominantAffect(-9, -9), 'tired');
});

test('fuseUserAffect: no usable source returns null', () => {
  assert.equal(fuseUserAffect({}), null);
  assert.equal(fuseUserAffect(), null);
  assert.equal(fuseUserAffect({ audio: { valence: 0.4, arousal: 0.4, confidence: 0 } }), null);
  assert.equal(fuseUserAffect({ face: null, audio: null }), null);
});

test('fuseUserAffect: audio-only keeps the audio source and fills the label', () => {
  const fused = fuseUserAffect({ audio: { valence: 0.5, arousal: 0.8, confidence: 0.6 } });
  assert.equal(fused.source, 'audio');
  assert.equal(fused.primary, 'excited');
  assert.equal(fused.confidence, 0.6);
});

test('fuseUserAffect: a labeled reading keeps its own primary', () => {
  const fused = fuseUserAffect({ audio: { primary: 'bored', valence: 0.5, arousal: 0.1, confidence: 0.4 } });
  assert.equal(fused.primary, 'bored');
});

test('fuseUserAffect: face + audio blend by confidence', () => {
  const fused = fuseUserAffect({
    face: { valence: 1, arousal: 0, confidence: 1 },
    audio: { valence: -1, arousal: 1, confidence: 1 },
  });
  assert.equal(fused.source, 'face+audio');
  assert.ok(Math.abs(fused.valence) < 1e-6, 'symmetric blend cancels valence');
  assert.ok(Math.abs(fused.arousal - 0.5) < 1e-6, 'arousal is the mean');
  assert.equal(fused.confidence, 1);
});

test('fuseUserAffect: a more confident source dominates the blend', () => {
  const fused = fuseUserAffect({
    face: { valence: 1, arousal: 0, confidence: 3 },
    audio: { valence: -1, arousal: 0, confidence: 1 },
  });
  assert.ok(fused.valence > 0, `expected face to dominate, got ${fused.valence}`);
});

test('resting references stay in a sane range', () => {
  assert.ok(AUDIO_REFS.pitchMid > 0 && AUDIO_REFS.pitchMid < 1);
  assert.ok(AUDIO_REFS.energyMid > 0 && AUDIO_REFS.energyMid < AUDIO_REFS.energySpan);
});
