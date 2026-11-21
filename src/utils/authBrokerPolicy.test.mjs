import test from 'node:test';
import assert from 'node:assert/strict';

import {
  isAllowedBackendUrl,
  stripRendererAuthorization,
} from './authBrokerPolicy.js';

const BACKEND = 'http://127.0.0.1:8000';

test('the configured backend is always allowed', () => {
  assert.equal(isAllowedBackendUrl(`${BACKEND}/api/system/health`, BACKEND), true);
});

test('loopback on the backend port is allowed', () => {
  assert.equal(isAllowedBackendUrl('http://localhost:8000/api/x', BACKEND), true);
  assert.equal(isAllowedBackendUrl('http://[::1]:8000/api/x', BACKEND), true);
});

test('other hosts, ports and schemes are rejected', () => {
  assert.equal(isAllowedBackendUrl('http://evil.example:8000/api/x', BACKEND), false);
  assert.equal(isAllowedBackendUrl('http://127.0.0.1:9000/api/x', BACKEND), false);
  assert.equal(isAllowedBackendUrl('https://example.com/api/x', BACKEND), false);
  assert.equal(isAllowedBackendUrl('file:///etc/passwd', BACKEND), false);
  assert.equal(isAllowedBackendUrl('not a url', BACKEND), false);
});

test('renderer-supplied Authorization is stripped', () => {
  const headers = stripRendererAuthorization({
    Authorization: 'Bearer attacker',
    authorization: 'Bearer attacker',
    'Content-Type': 'application/json',
  });
  assert.deepEqual(headers, { 'Content-Type': 'application/json' });
});

test('stripping never mutates the input object', () => {
  const input = { Authorization: 'Bearer attacker' };
  stripRendererAuthorization(input);
  assert.deepEqual(input, { Authorization: 'Bearer attacker' });
});
