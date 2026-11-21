import test from 'node:test';
import assert from 'node:assert/strict';

import {
  DeviceAuthError,
  createWsTicket,
  getServerAuthMode,
  hasCredential,
  loadCredential,
  personalFetch,
  storeCredential,
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

// ── Electron main-process auth broker ───────────────────────────────────────

function withElectronAPI(api, run) {
  const previous = globalThis.window;
  globalThis.window = {
    location: undefined,
    electronAPI: api,
    dispatchEvent: () => true,
  };
  return Promise.resolve()
    .then(run)
    .finally(() => {
      if (previous === undefined) delete globalThis.window;
      else globalThis.window = previous;
    });
}

test('hasCredential asks the main process instead of reading a secret', async () => {
  let asked = 0;
  await withElectronAPI(
    {
      hasDeviceCredential: async () => {
        asked += 1;
        return true;
      },
    },
    async () => {
      assert.equal(await hasCredential(), true);
      assert.equal(asked, 1);
    },
  );
});

test('personalFetch delegates authenticated requests to the broker', async () => {
  const calls = [];
  await withElectronAPI(
    {
      hasDeviceCredential: async () => true,
      authFetch: async (request) => {
        calls.push(request);
        return {
          ok: true,
          status: 200,
          body: '{"mode":"device"}',
          contentType: 'application/json',
        };
      },
    },
    async () => {
      const response = await personalFetch(
        'http://127.0.0.1:8000/api/system/health',
        { headers: { 'Content-Type': 'application/json' } },
      );
      assert.equal(response.status, 200);
      assert.deepEqual(await response.json(), { mode: 'device' });
    },
  );

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'http://127.0.0.1:8000/api/system/health');
  // The renderer never supplies the credential; the main process attaches it.
  assert.equal(calls[0].headers.Authorization, undefined);
});

test('broker ticket failure in strict mode clears the credential and asks for pairing', async () => {
  let cleared = 0;
  let pairingEvents = 0;
  const previous = globalThis.window;
  globalThis.window = {
    location: undefined,
    electronAPI: {
      hasDeviceCredential: async () => false,
      createWsTicket: async () => ({
        ok: false,
        status: 401,
        detail: 'Pair this computer before connecting to Aariya',
      }),
      clearDeviceCredential: async () => {
        cleared += 1;
        return true;
      },
    },
    dispatchEvent: () => {
      pairingEvents += 1;
      return true;
    },
  };
  try {
    await assert.rejects(
      createWsTicket('/ws/synoptics'),
      (error) =>
        error instanceof DeviceAuthError &&
        error.status === 401 &&
        /pair/i.test(error.message),
    );
    assert.equal(cleared, 1);
    assert.equal(pairingEvents, 1);
  } finally {
    if (previous === undefined) delete globalThis.window;
    else globalThis.window = previous;
  }
});

test('storing a credential in Electron never keeps the plaintext in renderer memory', async () => {
  await withElectronAPI(
    {
      hasDeviceCredential: async () => true,
      storeDeviceCredential: async () => true,
    },
    async () => {
      assert.equal(await storeCredential('aariya-device.secret'), true);
      assert.equal(await loadCredential(), null);
    },
  );
});
