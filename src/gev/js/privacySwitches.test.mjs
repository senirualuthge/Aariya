// Tests for the system-wide microphone/camera kill switches (ToDo §5).
//
// The unit under test is src/utils/privacySwitches.js. Two things have to hold:
//   1. a blocked device refuses a NEW getUserMedia request, and
//   2. a blocked device STOPS tracks that are already live — flipping the switch
//      is otherwise a no-op, because an already-running stream keeps recording.
//
// The module keeps state at module scope and installs a one-shot interceptor on
// navigator.mediaDevices, so each test loads a fresh instance (cache-busting
// query) against a fake mediaDevices object.

import assert from 'node:assert/strict';
import test from 'node:test';

// Fresh instance per test: module-level overrides, the "interceptor installed"
// flag and the stream registry must not leak between cases.
const counter = { n: 0 };
function freshModule() {
    counter.n += 1;
    return import(`../../utils/privacySwitches.js?n=${counter.n}`);
}

function fakeStream(kinds) {
    const tracks = kinds.map((kind) => {
        let stopped = false;
        return {
            kind,
            get stopped() { return stopped; },
            stop() { stopped = true; },
            addEventListener() {},
        };
    });
    return { getTracks: () => tracks, tracks };
}

/** Install a fake navigator whose getUserMedia records whether it was reached. */
function useFakeDevice(stream = null) {
    const calls = [];
    // Node 22 exposes `navigator` as a getter-only global, so it has to be
    // redefined rather than assigned.
    Object.defineProperty(globalThis, 'navigator', {
        configurable: true,
        writable: true,
        value: {
            mediaDevices: {
                getUserMedia: async (constraints) => {
                    calls.push(constraints);
                    return stream;
                },
            },
        },
    });
    return calls;
}

test('capture is allowed by default before the server is consulted', async () => {
    const mod = await freshModule();
    assert.equal(mod.isCaptureAllowed('microphone'), true);
    assert.equal(mod.isCaptureAllowed('camera'), true);
});

test('blocking the microphone refuses a new audio capture request', async () => {
    const mod = await freshModule();
    const calls = useFakeDevice(fakeStream(['audio']));

    // loadCaptureState installs the interceptor over the fake device.
    await mod.loadCaptureState();
    await mod.setCaptureEnabled('microphone', false);

    await assert.rejects(
        () => globalThis.navigator.mediaDevices.getUserMedia({ audio: true }),
        /microphone is switched off/i,
    );
    assert.equal(calls.length, 0, 'the real getUserMedia must not be reached');
});

test('camera stays usable while the microphone is blocked', async () => {
    const mod = await freshModule();
    const stream = fakeStream(['video']);
    useFakeDevice(stream);

    await mod.loadCaptureState();
    await mod.setCaptureEnabled('microphone', false);

    const granted = await globalThis.navigator.mediaDevices.getUserMedia({ video: true });
    assert.equal(granted, stream, 'camera request should pass through untouched');
});

test('blocking a device stops tracks that are already live', async () => {
    const mod = await freshModule();
    const stream = fakeStream(['video']);
    useFakeDevice(stream);

    await mod.loadCaptureState();
    await globalThis.navigator.mediaDevices.getUserMedia({ video: true });
    assert.equal(stream.tracks.some((t) => t.stopped), false);

    await mod.setCaptureEnabled('camera', false);
    assert.equal(stream.tracks.every((t) => t.stopped), true, 'live camera track must be stopped');
});

test('a microphone-only stream is stopped by the microphone switch alone', async () => {
    const mod = await freshModule();
    const stream = fakeStream(['audio']);
    useFakeDevice(stream);

    await mod.loadCaptureState();
    await globalThis.navigator.mediaDevices.getUserMedia({ audio: true });

    await mod.setCaptureEnabled('camera', false);      // wrong switch
    assert.equal(stream.tracks.some((t) => t.stopped), false);

    await mod.setCaptureEnabled('microphone', false);  // right switch
    assert.equal(stream.tracks.every((t) => t.stopped), true);
});

test('video: false is not mistaken for a camera request', async () => {
    const mod = await freshModule();
    const stream = fakeStream(['audio']);
    useFakeDevice(stream);

    await mod.loadCaptureState();
    await mod.setCaptureEnabled('camera', false);

    const granted = await globalThis.navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    assert.equal(granted, stream);
});

test('listeners are notified on change and stop after unsubscribing', async () => {
    const mod = await freshModule();
    useFakeDevice(fakeStream(['audio']));
    await mod.loadCaptureState();

    let latest = null;
    const off = mod.onCaptureChange((snapshot) => { latest = snapshot; });

    await mod.setCaptureEnabled('microphone', false);
    assert.deepEqual(latest, { microphone: false, camera: true });

    off();
    await mod.setCaptureEnabled('microphone', true);
    assert.deepEqual(latest, { microphone: false, camera: true }, 'unsubscribed listener must not fire');
});

test('an unreachable server leaves capture alone', async () => {
    const mod = await freshModule();
    useFakeDevice(fakeStream(['audio']));
    globalThis.fetch = async () => { throw new Error('offline'); };

    const state = await mod.loadCaptureState();
    assert.deepEqual(state, { microphone: true, camera: true });
});