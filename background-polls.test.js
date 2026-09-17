import test from 'node:test';
import assert from 'node:assert/strict';
import { schedulePredictorPoll, startUptimeTicker } from './src/utils/backgroundPolls.js';

// ── Stubs ──────────────────────────────────────────────────────────────────
// Spy that records every call (and returns undefined, like a bare callback).
function makeSpy() {
    const calls = [];
    const fn = (...args) => { calls.push(args); return undefined; };
    fn.calls = calls;
    return fn;
}

// A subscribe stub that records calls and returns an unsubscribe spy.
function makeSubscriber() {
    const calls = [];
    const unsub = makeSpy();
    const subscribe = (...args) => { calls.push(args); return unsub; };
    subscribe.calls = calls;
    subscribe.unsub = unsub;
    return subscribe;
}

// An interval stub that records (fn, ms) and returns a fake timer id.
function makeIntervalStub() {
    const calls = [];
    const setIntervalImpl = (fn, ms) => { calls.push({ fn, ms }); return { id: calls.length }; };
    setIntervalImpl.calls = calls;
    return setIntervalImpl;
}

// ── schedulePredictorPoll ──────────────────────────────────────────────────
test('schedulePredictorPoll: disabled ⇒ schedules nothing (no poll, no subscribe, no interval)', () => {
    const poll = makeSpy();
    const subscribe = makeSubscriber();
    const setIntervalImpl = makeIntervalStub();
    const clearIntervalImpl = makeSpy();

    const cleanup = schedulePredictorPoll({
        enabled: false, poll, subscribe,
        setIntervalImpl, clearIntervalImpl,
    });

    assert.equal(cleanup, null, 'disabled must return null cleanup');
    assert.equal(poll.calls.length, 0, 'initial poll must not fire when disabled');
    assert.equal(subscribe.calls.length, 0, 'model_trained subscription must not be created when disabled');
    assert.equal(setIntervalImpl.calls.length, 0, 'no interval may be scheduled when disabled');
    assert.equal(clearIntervalImpl.calls.length, 0);
});

test('schedulePredictorPoll: enabled ⇒ initial poll + interval + subscription, cleanup stops them', () => {
    const poll = makeSpy();
    const subscribe = makeSubscriber();
    const setIntervalImpl = makeIntervalStub();
    const clearIntervalImpl = makeSpy();

    const cleanup = schedulePredictorPoll({
        enabled: true, pollMs: 15000, poll, subscribe,
        setIntervalImpl, clearIntervalImpl,
    });

    assert.equal(typeof cleanup, 'function', 'enabled must return a cleanup');
    assert.equal(poll.calls.length, 1, 'one immediate poll on enable');
    assert.equal(subscribe.calls.length, 1, 'subscription created once');
    assert.equal(setIntervalImpl.calls.length, 1);
    assert.equal(setIntervalImpl.calls[0].ms, 15000, 'interval uses the poll interval');
    assert.equal(setIntervalImpl.calls[0].fn, poll, 'interval ticks the poll routine');

    const timer = setIntervalImpl.calls[0].fn; // sanity: same fn
    assert.equal(typeof timer, 'function');

    cleanup();
    assert.equal(clearIntervalImpl.calls.length, 1, 'cleanup clears the timer');
    assert.equal(subscribe.unsub.calls.length, 1, 'cleanup unsubscribes');
});

test('schedulePredictorPoll: honors a custom pollMs', () => {
    const setIntervalImpl = makeIntervalStub();
    schedulePredictorPoll({
        enabled: true, pollMs: 30000, poll: makeSpy(), subscribe: makeSubscriber(),
        setIntervalImpl, clearIntervalImpl: makeSpy(),
    });
    assert.equal(setIntervalImpl.calls[0].ms, 30000);
});

// ── startUptimeTicker ──────────────────────────────────────────────────────
test('startUptimeTicker: disabled ⇒ no timer is scheduled', () => {
    const onTick = makeSpy();
    const setIntervalImpl = makeIntervalStub();
    const clearIntervalImpl = makeSpy();

    const cleanup = startUptimeTicker({
        enabled: false, onTick,
        setIntervalImpl, clearIntervalImpl,
    });

    assert.equal(cleanup, null, 'disabled must return null cleanup');
    assert.equal(setIntervalImpl.calls.length, 0, 'no 1s ticker may run when disabled');
    assert.equal(onTick.calls.length, 0);
});

test('startUptimeTicker: enabled ⇒ 1s ticker calls onTick with elapsed seconds; cleanup stops it', () => {
    let now = 1000; // injectable clock
    const onTick = makeSpy();
    let tickCb = null;
    let tickMs = null;
    const setIntervalImpl = (fn, ms) => { tickCb = fn; tickMs = ms; return 42; };
    const clearIntervalImpl = makeSpy();

    const cleanup = startUptimeTicker({
        enabled: true, nowImpl: () => now, onTick,
        setIntervalImpl, clearIntervalImpl,
    });

    assert.equal(typeof cleanup, 'function');
    assert.equal(tickMs, 1000, 'uptime ticks once per second');
    assert.equal(onTick.calls.length, 0, 'no tick before the first interval fires');

    now = 1500; tickCb();
    assert.deepEqual(onTick.calls[0], [0], '0s elapsed after half a second');

    now = 2500; tickCb();
    assert.deepEqual(onTick.calls[1], [1], '1s elapsed after 1.5s');

    cleanup();
    assert.deepEqual(clearIntervalImpl.calls, [[42]], 'cleanup clears the ticker');
});
