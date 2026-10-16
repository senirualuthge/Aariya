// Tests for the frontend user-identity provider (Track A of the partials plan).
// Runs under `node --test` — no browser required. localStorage is simulated so
// both the storage-backed and the in-memory fallback paths are exercised.
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  getUserId,
  setUserId,
  subscribeUserId,
  generateUserId,
  _resetUserIdentityForTests,
  STORAGE_KEY,
  FALLBACK_USER_ID,
} from './userIdentity.js';

test('getUserId returns a stable generated id, never the legacy literal', () => {
  _resetUserIdentityForTests();
  const a = getUserId();
  const b = getUserId();
  assert.equal(a, b, 'id is stable across calls');
  assert.ok(a.length > 0, 'id is non-empty');
  assert.notEqual(a, FALLBACK_USER_ID, 'must not collapse onto user_default');
  assert.match(a, /^user_/, 'ids are namespaced with the user_ prefix');
});

test('setUserId round-trips and notifies subscribers exactly once per change', () => {
  _resetUserIdentityForTests();
  const seen = [];
  const unsub = subscribeUserId((id) => seen.push(id));

  assert.equal(setUserId('alice'), 'alice');
  assert.equal(getUserId(), 'alice');
  assert.deepEqual(seen, ['alice'], 'one notification for the change');

  setUserId('alice'); // unchanged → no-op
  assert.deepEqual(seen, ['alice'], 're-setting the same id does not notify');

  unsub();
  setUserId('bob');
  assert.deepEqual(seen, ['alice'], 'unsubscribed listeners stop receiving');
  assert.equal(getUserId(), 'bob');
});

test('setUserId falls back to the legacy id for blank input', () => {
  _resetUserIdentityForTests();
  setUserId('   ');
  assert.equal(getUserId(), FALLBACK_USER_ID);
});

test('persists to and restores from localStorage when available', () => {
  const store = new Map();
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  };
  try {
    _resetUserIdentityForTests();
    const id = getUserId();
    assert.equal(store.get(STORAGE_KEY), id, 'fresh id is written to storage');

    // Simulate a reload: drop the module cache but keep storage.
    _resetUserIdentityForTests();
    assert.equal(getUserId(), id, 'returning user keeps their identity');

    // A pre-seeded id wins over generation.
    store.set(STORAGE_KEY, 'preset-user');
    _resetUserIdentityForTests();
    assert.equal(getUserId(), 'preset-user');
  } finally {
    delete globalThis.localStorage;
  }
});

test('generateUserId produces unique ids', () => {
  const ids = new Set(Array.from({ length: 50 }, () => generateUserId()));
  assert.equal(ids.size, 50);
});
