// Tests for the person-identity registry (src/systems/personIdentity.js).
//
// face-api's descriptor is a 128-d vector; matching is euclidean distance with
// the library's own 0.6 threshold. These tests build descriptors by hand
// (deterministic, no model weights) so the whole identification/enrolment/
// persistence/background-search surface is verified without a camera.

import assert from 'node:assert/strict';
import test from 'node:test';

import {
    DESCRIPTOR_LENGTH,
    IdentityRegistry,
    createPendingPerson,
    descriptorDistance,
    toDescriptor,
} from '../../systems/personIdentity.js';

class FakeStorage {
    constructor() { this.map = new Map(); }
    getItem(k) { return this.map.has(k) ? this.map.get(k) : null; }
    setItem(k, v) { this.map.set(k, String(v)); }
    removeItem(k) { this.map.delete(k); }
}

/** Deterministic unit-ish vector: stable per seed, never all-equal to another. */
function descriptor(seed = 0, scale = 1) {
    const out = new Array(DESCRIPTOR_LENGTH);
    for (let i = 0; i < DESCRIPTOR_LENGTH; i += 1) {
        out[i] = ((Math.sin(seed * 12.9898 + i * 78.233) * 43758.5453) % 1) * scale;
    }
    return out;
}

/** A vector `offset` away from `base` — a controlled distance. */
function perturb(base, offset, dims = 4) {
    const out = [...base];
    for (let i = 0; i < dims; i += 1) out[i] += offset;
    return out;
}

const newRegistry = (overrides = {}) =>
    new IdentityRegistry({ storage: new FakeStorage(), now: () => 1_700_000_000_000, ...overrides });

// ── descriptor plumbing ──────────────────────────────────────────────────────

test('toDescriptor accepts arrays and typed arrays, rejects everything else', () => {
    assert.equal(toDescriptor(descriptor(1)).length, DESCRIPTOR_LENGTH);
    assert.equal(toDescriptor(Float32Array.from(descriptor(2))).length, DESCRIPTOR_LENGTH);
    assert.equal(toDescriptor(null), null);
    assert.equal(toDescriptor(descriptor(1).slice(0, 10)), null, 'wrong length rejected');
    assert.equal(toDescriptor([1, 2, NaN]), null);
});

test('descriptorDistance is euclidean and rejects mismatched vectors', () => {
    assert.equal(descriptorDistance([0, 0], [3, 4]), 5);
    assert.equal(descriptorDistance([0, 0], [0, 0]), 0);
    assert.equal(descriptorDistance([0], [0, 0]), null);
    assert.equal(descriptorDistance(null, [0]), null);
});

// ── identification ───────────────────────────────────────────────────────────

test('an empty registry never claims to know anyone', () => {
    const reg = newRegistry();
    const result = reg.identify(descriptor(1));
    assert.equal(result.status, 'new');
    assert.equal(result.profile, null);
});

test('an enrolled face is recognised as known', () => {
    const reg = newRegistry();
    reg.enroll(descriptor(1), { name: 'Ada' });
    const result = reg.identify(descriptor(1));
    assert.equal(result.status, 'known');
    assert.equal(result.profile.name, 'Ada');
});

test('a close-but-not-identical face is reported uncertain, not known', () => {
    const reg = newRegistry();
    reg.enroll(descriptor(1), { name: 'Ada' });
    // distance = 0.24 * sqrt(8) = 0.68: past the 0.6 threshold, inside the
    // 0.75 uncertain band.
    const result = reg.identify(perturb(descriptor(1), 0.24, 8));
    assert.equal(result.status, 'uncertain');
    assert.equal(result.profile.name, 'Ada');
    assert.ok(result.candidate, 'uncertain result carries the candidate for confirmation');
});

test('a stranger is never silently enrolled', () => {
    const reg = newRegistry();
    reg.enroll(descriptor(1), { name: 'Ada' });
    const result = reg.identify(descriptor(99));
    assert.equal(result.status, 'new');
    assert.equal(reg.list().length, 1, 'registry must not grow on an unknown face');
});

test('identify does not mutate the caller descriptor', () => {
    const reg = newRegistry();
    const vector = descriptor(1);
    const copy = [...vector];
    reg.enroll(descriptor(2), { name: 'Grace' });
    reg.identify(vector);
    assert.deepEqual(vector, copy);
});

test('repeated sightings tighten the profile and update bookkeeping', () => {
    let clock = 1_700_000_000_000;
    const reg = newRegistry({ now: () => clock });
    reg.enroll(descriptor(1), { name: 'Ada' });
    const before = reg.list()[0];

    clock += 60_000;
    reg.identify(perturb(descriptor(1), 0.2, 4));

    const after = reg.list()[0];
    assert.equal(after.sightingCount, before.sightingCount + 1);
    assert.equal(after.lastSeenAt, clock);
    assert.notDeepEqual(after.descriptor, before.descriptor, 'descriptor is folded toward the new sighting');
});

test('identify returns a defensive copy of the profile', () => {
    const reg = newRegistry();
    reg.enroll(descriptor(1), { name: 'Ada' });
    const first = reg.identify(descriptor(1));
    first.profile.name = 'Mutated';
    assert.equal(reg.list()[0].name, 'Ada');
});

// ── enrolment and editing ────────────────────────────────────────────────────

test('enroll rejects an unusable descriptor', () => {
    const reg = newRegistry();
    assert.throws(() => reg.enroll([1, 2, 3]), /128-dimensional/);
    assert.throws(() => reg.enroll(null), /128-dimensional/);
});

test('enroll defaults an empty name rather than storing a blank one', () => {
    const reg = newRegistry();
    assert.equal(reg.enroll(descriptor(1), { name: '   ' }).name, 'Unknown person');
});

test('enroll with an existing id updates in place instead of duplicating', () => {
    const reg = newRegistry();
    const first = reg.enroll(descriptor(1), { name: 'Ada', id: 'fixed' });
    reg.enroll(descriptor(2), { name: 'Ada Lovelace', id: 'fixed' });
    const list = reg.list();
    assert.equal(list.length, 1);
    assert.equal(list[0].name, 'Ada Lovelace');
    assert.equal(list[0].id, first.id);
});

test('rename and addNote update the profile', () => {
    const reg = newRegistry();
    const { id } = reg.enroll(descriptor(1), { name: 'Ada' });
    assert.equal(reg.rename(id, 'Ada Lovelace').name, 'Ada Lovelace');
    reg.addNote(id, 'met at the conference');
    reg.addNote(id, 'follows the GEV work');
    assert.match(reg.get(id).notes, /conference\nfollows the GEV work/);
    assert.equal(reg.rename('nope', 'x'), null);
});

test('forget removes a person and clear empties the registry', () => {
    const reg = newRegistry();
    const { id } = reg.enroll(descriptor(1), { name: 'Ada' });
    reg.enroll(descriptor(2), { name: 'Grace' });
    assert.equal(reg.forget(id), true);
    assert.equal(reg.forget(id), false, 'forgetting twice is a no-op');
    assert.equal(reg.list().length, 1);
    reg.clear();
    assert.equal(reg.list().length, 0);
});

// ── persistence ──────────────────────────────────────────────────────────────

test('profiles survive a reload from storage', () => {
    const storage = new FakeStorage();
    const first = new IdentityRegistry({ storage, now: () => 42 });
    first.enroll(descriptor(1), { name: 'Ada', notes: 'engineer' });

    const second = new IdentityRegistry({ storage, now: () => 99 });
    assert.equal(second.list().length, 1);
    assert.equal(second.list()[0].name, 'Ada');
    assert.equal(second.list()[0].notes, 'engineer');
    assert.equal(second.identify(descriptor(1)).status, 'known');
});

test('a corrupt storage payload degrades to an empty registry', () => {
    const storage = new FakeStorage();
    storage.setItem('aariya.knownPeople.v1', '{not json');
    assert.deepEqual(new IdentityRegistry({ storage }).list(), []);

    storage.setItem('aariya.knownPeople.v1', '[{"id":"x","descriptor":[1,2,3]}]');
    assert.deepEqual(new IdentityRegistry({ storage }).list(), [], 'short descriptors are dropped');
});

// ── background search ────────────────────────────────────────────────────────

test('background search resolves with the search result', async () => {
    const reg = newRegistry();
    const { id } = reg.enroll(descriptor(1), { name: 'Ada' });
    const found = await reg.searchInBackground(reg.get(id), async () => ['note-1']);
    assert.deepEqual(found, ['note-1']);
});

test('concurrent searches for one person are deduplicated', async () => {
    const reg = newRegistry();
    const { id } = reg.enroll(descriptor(1), { name: 'Ada' });
    let calls = 0;
    const search = async () => {
        calls += 1;
        await new Promise((r) => setTimeout(r, 20));
        return 'ok';
    };
    const profile = reg.get(id);
    await Promise.all([
        reg.searchInBackground(profile, search),
        reg.searchInBackground(profile, search),
        reg.searchInBackground(profile, search),
    ]);
    assert.equal(calls, 1, 'a face held in frame must not launch one search per frame');
});

test('a failing or slow background search resolves to null instead of throwing', async () => {
    const reg = newRegistry();
    const { id } = reg.enroll(descriptor(1), { name: 'Ada' });
    const profile = reg.get(id);

    const failed = await reg.searchInBackground(profile, async () => { throw new Error('boom'); });
    assert.equal(failed, null);

    const slow = await reg.searchInBackground(reg.get(id), () => new Promise(() => {}), { timeoutMs: 20 });
    assert.equal(slow, null, 'a hung search times out rather than wedging the UI');
});

test('search can be retried after a failure', async () => {
    const reg = newRegistry();
    const { id } = reg.enroll(descriptor(1), { name: 'Ada' });
    const profile = reg.get(id);
    await reg.searchInBackground(profile, async () => { throw new Error('boom'); });
    assert.equal(await reg.searchInBackground(reg.get(id), async () => 'second time'), 'second time');
});

// ── pending person ───────────────────────────────────────────────────────────

test('createPendingPerson keeps an unnamed stranger out of the registry', () => {
    const pending = createPendingPerson(descriptor(1), 1234);
    assert.equal(pending.enrolled, false);
    assert.equal(pending.name, '');
    assert.equal(pending.descriptor.length, DESCRIPTOR_LENGTH);
});

// ── events ───────────────────────────────────────────────────────────────────

test('subscribers see enrol, rename and forget events', () => {
    const reg = newRegistry();
    const events = [];
    const off = reg.subscribe((e) => events.push(e.type));

    const { id } = reg.enroll(descriptor(1), { name: 'Ada' });
    reg.rename(id, 'Ada L');
    reg.forget(id);
    off();
    reg.enroll(descriptor(2), { name: 'Grace' });

    assert.deepEqual(events, ['enrolled', 'renamed', 'forgotten']);
});

test('a throwing subscriber does not break the registry', () => {
    const reg = newRegistry();
    reg.subscribe(() => { throw new Error('bad listener'); });
    const seen = [];
    reg.subscribe(() => seen.push('ok'));
    assert.doesNotThrow(() => reg.enroll(descriptor(1), { name: 'Ada' }));
    assert.deepEqual(seen, ['ok']);
});