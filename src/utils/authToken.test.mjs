import test from 'node:test';
import assert from 'node:assert/strict';

import {
  TOKEN_STORAGE_KEY,
  authHeaders,
  authToken,
  wsUrlWithToken,
} from './authToken.js';

test('no token configured -> no Authorization header', () => {
  globalThis.localStorage = { getItem: () => null };
  try {
    assert.equal(authToken(), '');
    assert.deepEqual(authHeaders({ Accept: 'application/json' }), {
      Accept: 'application/json',
    });
  } finally {
    delete globalThis.localStorage;
  }
});

test('stored token is trimmed, used as Bearer, extra headers preserved', () => {
  globalThis.localStorage = {
    getItem: (key) => (key === TOKEN_STORAGE_KEY ? '  s3cret  ' : null),
  };
  try {
    assert.equal(authToken(), 's3cret');
    assert.deepEqual(authHeaders({ Accept: 'application/json' }), {
      Accept: 'application/json',
      Authorization: 'Bearer s3cret',
    });
  } finally {
    delete globalThis.localStorage;
  }
});

test('blank stored token falls through instead of sending "Bearer "', () => {
  globalThis.localStorage = { getItem: () => '   ' };
  try {
    assert.equal(authToken(), '');
    assert.deepEqual(authHeaders(), {});
  } finally {
    delete globalThis.localStorage;
  }
});

function _withStoredToken(token, fn) {
  globalThis.localStorage = {
    getItem: (key) => (key === TOKEN_STORAGE_KEY ? token : null),
  };
  try {
    fn();
  } finally {
    delete globalThis.localStorage;
  }
}

test('websocket url is unchanged when no token is configured', () => {
  _withStoredToken(null, () => {
    assert.equal(
      wsUrlWithToken('ws://127.0.0.1:8000/ws/synoptics'),
      'ws://127.0.0.1:8000/ws/synoptics'
    );
  });
});

test('websocket url gains the token as a query param', () => {
  _withStoredToken('tok123', () => {
    assert.equal(
      wsUrlWithToken('ws://127.0.0.1:8000/ws/synoptics'),
      'ws://127.0.0.1:8000/ws/synoptics?token=tok123'
    );
  });
});

test('websocket url keeps existing query params', () => {
  _withStoredToken('tok123', () => {
    assert.equal(
      wsUrlWithToken('ws://127.0.0.1:8000/ws/dashboard/stream?user_id=u1'),
      'ws://127.0.0.1:8000/ws/dashboard/stream?user_id=u1&token=tok123'
    );
  });
});

test('websocket url token is percent-encoded', () => {
  _withStoredToken('tok/en +?', () => {
    assert.equal(
      wsUrlWithToken('ws://127.0.0.1:8000/ws/synoptics'),
      'ws://127.0.0.1:8000/ws/synoptics?token=tok%2Fen+%2B%3F'
    );
  });
});

test('relative websocket url falls back to string concatenation', () => {
  _withStoredToken('tok123', () => {
    assert.equal(wsUrlWithToken('/ws/synoptics'), '/ws/synoptics?token=tok123');
    assert.equal(wsUrlWithToken('/ws/x?user_id=u1'), '/ws/x?user_id=u1&token=tok123');
  });
});

test('blocked localStorage does not throw', () => {
  globalThis.localStorage = {
    getItem: () => {
      throw new Error('storage blocked');
    },
  };
  try {
    assert.equal(authToken(), '');
    assert.deepEqual(authHeaders(), {});
  } finally {
    delete globalThis.localStorage;
  }
});
