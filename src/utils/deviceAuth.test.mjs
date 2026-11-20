import test from 'node:test';
import assert from 'node:assert/strict';

import {
  DeviceAuthError,
  createWsTicket,
  getServerAuthMode,
} from './deviceAuth.js';

function _modeResponse(enabled) {
  return {
    ok: true,
    status: 200,
    json: async () => ({ device_auth_enabled: enabled }),
  };
}

test('auth mode is read from the server mode endpoint', async () => {
  const original = globalThis.fetch;
  let requested = '';
  globalThis.fetch = async (url) => {
    requested = String(url);
    return _modeResponse(true);
  };
  try {
    assert.equal(await getServerAuthMode(), true);
    assert.match(requested, /\/api\/auth\/mode$/);
  } finally {
    globalThis.fetch = original;
  }
});

test('invalid auth-mode payload is rejected', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: true,
    status: 200,
    json: async () => ({ mode: 'device' }),
  });
  try {
    await assert.rejects(getServerAuthMode(), DeviceAuthError);
  } finally {
    globalThis.fetch = original;
  }
});

test('missing credential in strict mode requires pairing', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => _modeResponse(true);
  try {
    await assert.rejects(
      createWsTicket('/ws/synoptics'),
      (error) =>
        error instanceof DeviceAuthError &&
        error.status === 401 &&
        /pair/i.test(error.message),
    );
  } finally {
    globalThis.fetch = original;
  }
});

test('missing credential in legacy mode permits the legacy socket', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => _modeResponse(false);
  try {
    assert.equal(await createWsTicket('/ws/synoptics'), null);
  } finally {
    globalThis.fetch = original;
  }
});
