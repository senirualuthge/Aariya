import assert from 'node:assert/strict';
import test from 'node:test';

import { evaluateAudit } from './audit_gate.mjs';

const GHS_A = 'https://github.com/advisories/GHSA-hp3w-g68c-fv3c';
const GHS_B = 'https://github.com/advisories/GHSA-zzzz-1111-2222';

test('clean audit passes', () => {
  const result = evaluateAudit({ vulnerabilities: {} });
  assert.equal(result.ok, true);
  assert.equal(result.disallowed.length, 0);
});

test('missing report shape is treated as clean, not as a crash', () => {
  assert.equal(evaluateAudit({}).ok, true);
  assert.equal(evaluateAudit(undefined).ok, true);
});

test('the known sprintf-js advisory is accepted and keeps its reason', () => {
  const result = evaluateAudit({
    vulnerabilities: {
      'sprintf-js': {
        severity: 'moderate',
        via: [{ url: GHS_A, title: 'unbounded precision specifiers' }],
      },
    },
  });
  assert.equal(result.ok, true);
  assert.equal(result.accepted.length, 1);
  assert.equal(result.accepted[0].advisory, 'GHSA-hp3w-g68c-fv3c');
  assert.match(result.accepted[0].reason, /tfjs/);
});

test('an allow-listed package with a DIFFERENT advisory still fails', () => {
  const result = evaluateAudit({
    vulnerabilities: {
      'sprintf-js': {
        severity: 'high',
        via: [{ url: GHS_B, title: 'something new' }],
      },
    },
  });
  assert.equal(result.ok, false);
  assert.equal(result.disallowed[0].advisory, 'GHSA-zzzz-1111-2222');
});

test('an unlisted package fails even at low severity', () => {
  const result = evaluateAudit({
    vulnerabilities: {
      'left-pad': { severity: 'low', via: [{ url: GHS_B, title: 'padded' }] },
    },
  });
  assert.equal(result.ok, false);
  assert.equal(result.disallowed.length, 1);
});

test('one bad advisory among several fails even if another is allowed', () => {
  const result = evaluateAudit({
    vulnerabilities: {
      'sprintf-js': {
        severity: 'moderate',
        via: [{ url: GHS_A, title: 'allowed' }, { url: GHS_B, title: 'new' }],
      },
    },
  });
  assert.equal(result.ok, false);
  assert.equal(result.accepted.length, 1);
  assert.equal(result.disallowed.length, 1);
});

test('dependency-chain entries are not counted as separate findings', () => {
  // npm reports the chain as bare names alongside the advisory object; those
  // entries belong to the same finding and must not gate on their own.
  const result = evaluateAudit({
    vulnerabilities: {
      argparse: { severity: 'moderate', via: ['sprintf-js'] },
    },
  });
  assert.equal(result.ok, true);
  assert.equal(result.disallowed.length, 0);
  assert.equal(result.chains.length, 1);
  assert.equal(result.chains[0].dependsOn, 'sprintf-js');
});

test('the real-world tfjs chain is accepted end to end', () => {
  const result = evaluateAudit({
    vulnerabilities: {
      'sprintf-js': { severity: 'moderate', via: [{ url: GHS_A, title: 'DoS' }] },
      argparse: { severity: 'moderate', via: ['sprintf-js'] },
      '@tensorflow/tfjs': { severity: 'moderate', via: ['argparse'] },
    },
  });
  assert.equal(result.ok, true);
  assert.equal(result.accepted.length, 1, 'one advisory, not three findings');
  assert.equal(result.chains.length, 2);
});

test('an allowed advisory does not excuse a second real one', () => {
  const result = evaluateAudit({
    vulnerabilities: {
      'sprintf-js': { severity: 'moderate', via: [{ url: GHS_A, title: 'allowed' }] },
      'left-pad': { severity: 'high', via: [{ url: GHS_B, title: 'new' }] },
    },
  });
  assert.equal(result.ok, false);
  assert.equal(result.accepted.length, 1);
  assert.equal(result.disallowed[0].package, 'left-pad');
});