// Tests for the Meeting-Mode spatial-audio helpers (systems/spatialAudio.js).
// Runs under `node --test`: the pure slot→pan mapping is checked directly, and
// the WebAudio graph is exercised against a minimal fake AudioContext.
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  panForSlot,
  getSpatialContext,
  playPannedAudio,
  attachPanner,
  _resetSpatialAudioForTests,
} from './spatialAudio.js';

// ── panForSlot ───────────────────────────────────────────────────────────────

test('panForSlot: a single slot is centred', () => {
  assert.equal(panForSlot(0, 1), 0);
  assert.equal(panForSlot(0, 0), 0);
});

test('panForSlot: two slots split hard left / hard right', () => {
  assert.equal(panForSlot(0, 2), -1);
  assert.equal(panForSlot(1, 2), 1);
});

test('panForSlot: three slots are evenly spread', () => {
  assert.equal(panForSlot(0, 3), -1);
  assert.equal(panForSlot(1, 3), 0);
  assert.equal(panForSlot(2, 3), 1);
});

test('panForSlot: four slots are evenly spread', () => {
  assert.ok(Math.abs(panForSlot(0, 4) - -1) < 1e-9);
  assert.ok(Math.abs(panForSlot(1, 4) - -1 / 3) < 1e-9);
  assert.ok(Math.abs(panForSlot(2, 4) - 1 / 3) < 1e-9);
  assert.ok(Math.abs(panForSlot(3, 4) - 1) < 1e-9);
});

test('panForSlot: clamps bad input and never exceeds [-1, 1]', () => {
  assert.equal(panForSlot(9, 3), 1);
  assert.equal(panForSlot(-4, 3), -1);
  assert.equal(panForSlot(null, 3), 0);
  assert.equal(panForSlot(1, NaN), 0);
  assert.equal(panForSlot(NaN, 2), 0);
  for (let i = 0; i < 12; i++) {
    const p = panForSlot(i, 12);
    assert.ok(p >= -1 && p <= 1, `pan ${p} out of range`);
  }
});

// ── No-browser guards ────────────────────────────────────────────────────────

test('outside a browser every playback helper is an honest no-op', async () => {
  delete globalThis.window;
  _resetSpatialAudioForTests();
  assert.equal(getSpatialContext(), null);
  assert.equal(await playPannedAudio({}, 0.5), false);
  assert.equal(attachPanner({}, 0.5), null);
});

// ── WebAudio graph (fake context) ────────────────────────────────────────────

function installFakeAudioContext() {
  const graph = { panners: [], gains: [], started: 0, elementSources: [] };
  class FakeCtx {
    constructor() {
      this.state = 'running';
      this.destination = { name: 'dest' };
      this.sampleRate = 48000;
    }
    createBufferSource() {
      return { buffer: null, connect: (n) => n, start: () => { graph.started++; } };
    }
    createGain() {
      const g = { gain: { value: 1 }, connect: (n) => n };
      graph.gains.push(g);
      return g;
    }
    createStereoPanner() {
      const p = { pan: { value: 0 }, connect: (n) => n };
      graph.panners.push(p);
      return p;
    }
    createMediaElementSource(el) {
      const s = { el, connect: (n) => n };
      graph.elementSources.push(s);
      return s;
    }
    async decodeAudioData() { return { decoded: true }; }
    async resume() { this.state = 'running'; }
  }
  globalThis.window = { AudioContext: FakeCtx };
  _resetSpatialAudioForTests();
  return graph;
}

function uninstallFakeAudioContext() {
  delete globalThis.window;
  _resetSpatialAudioForTests();
}

test('playPannedAudio routes a real buffer through a StereoPannerNode', async () => {
  const graph = installFakeAudioContext();
  try {
    const ok = await playPannedAudio({ decoded: true }, panForSlot(2, 4));
    assert.equal(ok, true);
    assert.equal(graph.started, 1, 'source actually started');
    assert.equal(graph.panners.length, 1, 'a panner was created');
    assert.ok(Math.abs(graph.panners[0].pan.value - 1 / 3) < 1e-9, 'pan = slot pan');
  } finally {
    uninstallFakeAudioContext();
  }
});

test('playPannedAudio decodes a URL before playing', async () => {
  const graph = installFakeAudioContext();
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => ({ arrayBuffer: async () => new ArrayBuffer(8) });
  try {
    const ok = await playPannedAudio('https://example.test/reply.mp3', -1);
    assert.equal(ok, true);
    assert.equal(graph.panners[0].pan.value, -1);
  } finally {
    globalThis.fetch = realFetch;
    uninstallFakeAudioContext();
  }
});

test('playPannedAudio gives up when the URL fails to decode', async () => {
  installFakeAudioContext();
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => { throw new Error('offline'); };
  try {
    assert.equal(await playPannedAudio('https://example.test/missing.mp3', 0), false);
  } finally {
    globalThis.fetch = realFetch;
    uninstallFakeAudioContext();
  }
});

test('attachPanner is idempotent per element and updates the pan', () => {
  const graph = installFakeAudioContext();
  try {
    const el = {};
    const p1 = attachPanner(el, -1);
    const p2 = attachPanner(el, 1);
    assert.equal(p1, p2, 'same panner reused');
    assert.equal(graph.elementSources.length, 1, 'one MediaElementSource created');
    assert.equal(p2.pan.value, 1);
  } finally {
    uninstallFakeAudioContext();
  }
});
