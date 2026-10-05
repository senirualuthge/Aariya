// src/systems/personIdentity.js
//
// Person identification (ToDo §4): recognise a face against the people Aariya
// already knows, and when someone new arrives, kick off a background search
// and surface them for enrolment.
//
// face-api.js produces a 128-dimensional descriptor per detected face. Matching
// is plain euclidean distance — the reference implementation's own metric, with
// its documented 0.6 decision threshold. There is no model in this file and no
// inference: this module only owns the registry, the matching rules, the
// persistence, and the background-search lifecycle, which keeps it testable
// without a browser, a camera, or model weights.
//
// Identity data is biometric and therefore the most sensitive thing this app
// stores. Two consequences are deliberate:
//   - profiles never leave the device (localStorage by default, injected store
//     for tests); nothing here posts a descriptor anywhere;
//   - a profile is only ever matched, never guessed: below the threshold the
//     result is an explicit "new person" with no auto-enrolment, so a stranger
//     is never silently written into the registry.

export const DESCRIPTOR_LENGTH = 128;

/**
 * face-api.js's own decision threshold. Distances below this are the same
 * person; the band up to UNCERTAIN_BAND is reported as a low-confidence match
 * so the UI can ask instead of asserting.
 */
export const MATCH_THRESHOLD = 0.6;
export const UNCERTAIN_BAND = 0.75;

const STORAGE_KEY = 'aariya.knownPeople.v1';

/** Euclidean distance between two descriptors, or null if either is unusable. */
export function descriptorDistance(a, b) {
    if (!a || !b || a.length !== b.length || a.length === 0) return null;
    let sum = 0;
    for (let i = 0; i < a.length; i += 1) {
        const diff = a[i] - b[i];
        sum += diff * diff;
    }
    return Math.sqrt(sum);
}

/** Validate + normalise anything descriptor-shaped into a plain number array. */
export function toDescriptor(input) {
    if (!input) return null;
    const values = typeof input.length === 'number' && typeof input !== 'string'
        ? Array.from(input)
        : Array.isArray(input) ? input : null;
    if (!values || values.length !== DESCRIPTOR_LENGTH) return null;
    const out = new Array(DESCRIPTOR_LENGTH);
    for (let i = 0; i < DESCRIPTOR_LENGTH; i += 1) {
        const n = Number(values[i]);
        if (!Number.isFinite(n)) return null;
        out[i] = n;
    }
    return out;
}

/** localStorage-backed profile store, with an in-memory fallback for tests. */
function defaultStorage() {
    try {
        if (typeof localStorage === 'undefined' || !localStorage) return null;
        const probe = '__aariya_probe__';
        localStorage.setItem(probe, '1');
        localStorage.removeItem(probe);
        return localStorage;
    } catch {
        // Private-mode Safari / disabled storage: fall back to memory so the
        // feature degrades to "works until reload" instead of throwing.
        return null;
    }
}

class MemoryStorage {
    constructor() { this.map = new Map(); }
    getItem(key) { return this.map.has(key) ? this.map.get(key) : null; }
    setItem(key, value) { this.map.set(key, String(value)); }
    removeItem(key) { this.map.delete(key); }
}

export class IdentityRegistry {
    /**
     * @param {object} [options]
     * @param {object} [options.storage]  Storage-like (getItem/setItem).
     * @param {number} [options.threshold]
     * @param {() => number} [options.now]
     */
    constructor(options = {}) {
        this.storage = options.storage ?? defaultStorage() ?? new MemoryStorage();
        this.threshold = options.threshold ?? MATCH_THRESHOLD;
        this.uncertainBand = options.uncertainBand ?? UNCERTAIN_BAND;
        this.now = options.now ?? (() => Date.now());
        this.profiles = this._load();
        this.listeners = new Set();
        this.searches = new Map();
    }

    // ── persistence ──────────────────────────────────────────────────────────

    _load() {
        try {
            const raw = this.storage.getItem(STORAGE_KEY);
            if (!raw) return [];
            const parsed = JSON.parse(raw);
            if (!Array.isArray(parsed)) return [];
            return parsed
                .map((p) => this._sanitize(p))
                .filter(Boolean);
        } catch {
            // Corrupt payload — start clean rather than wedging the feature.
            return [];
        }
    }

    _sanitize(profile) {
        if (!profile || typeof profile !== 'object') return null;
        const descriptor = toDescriptor(profile.descriptor);
        if (!descriptor) return null;
        return {
            id: typeof profile.id === 'string' && profile.id ? profile.id : this._newId(),
            name: typeof profile.name === 'string' && profile.name.trim()
                ? profile.name.trim()
                : 'Unknown person',
            notes: typeof profile.notes === 'string' ? profile.notes : '',
            descriptor,
            createdAt: Number(profile.createdAt) || this.now(),
            lastSeenAt: Number(profile.lastSeenAt) || Number(profile.createdAt) || this.now(),
            sightingCount: Number(profile.sightingCount) || 1,
            enrolled: profile.enrolled === true,
        };
    }

    _persist() {
        try {
            this.storage.setItem(STORAGE_KEY, JSON.stringify(this.profiles));
            return true;
        } catch {
            // Quota exceeded (descriptors are ~1 KB of JSON each).
            return false;
        }
    }

    _newId() {
        const rand = Math.random().toString(36).slice(2, 8);
        return `person-${this.now().toString(36)}-${rand}`;
    }

    _emit(event) {
        for (const listener of this.listeners) {
            try {
                listener(event);
            } catch (err) {
                console.warn('[personIdentity] listener failed:', err);
            }
        }
    }

    /** Subscribe to registry events. Returns an unsubscribe function. */
    subscribe(listener) {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }

    // ── queries ──────────────────────────────────────────────────────────────

    list() {
        return this.profiles.map((p) => ({ ...p, descriptor: [...p.descriptor] }));
    }

    get(id) {
        const found = this.profiles.find((p) => p.id === id);
        return found ? { ...found, descriptor: [...found.descriptor] } : null;
    }

    /** Find the enrolled profile nearest to a descriptor, or null. */
    match(descriptor) {
        const candidate = toDescriptor(descriptor);
        if (!candidate) return null;
        let best = null;
        for (const profile of this.profiles) {
            const distance = descriptorDistance(candidate, profile.descriptor);
            if (distance === null) continue;
            if (!best || distance < best.distance) best = { profile, distance };
        }
        return best;
    }

    // ── the identification decision ──────────────────────────────────────────

    /**
     * Identify a face.
     *
     * @returns {{status:'known'|'uncertain'|'new', profile:object|null,
     *            distance:number|null, candidate:object|null}}
     *   known    — under the match threshold; the person is recognised.
     *   uncertain — in the band above it; a real match, but the UI should
     *              confirm rather than announce.
     *   new      — nobody is close enough. No profile is created here: a
     *              stranger must be enrolled deliberately.
     */
    identify(descriptor) {
        const candidate = toDescriptor(descriptor);
        if (!candidate) {
            return { status: 'new', profile: null, distance: null, candidate: null };
        }
        const best = this.match(candidate);
        if (!best || best.distance > this.uncertainBand) {
            return { status: 'new', profile: null, distance: best?.distance ?? null, candidate: null };
        }
        const profile = this._touch(best.profile, candidate);
        const status = best.distance <= this.threshold ? 'known' : 'uncertain';
        const result = {
            status,
            profile: { ...profile, descriptor: [...profile.descriptor] },
            distance: best.distance,
            candidate: status === 'uncertain' ? { ...profile, descriptor: undefined } : null,
        };
        this._emit({ type: 'identified', ...result });
        return result;
    }

    /**
     * Bump sighting bookkeeping and slowly fold the new descriptor in.
     * Averaging across sightings tightens the match over time; early sightings
     * dominate (weight ramps 0.2 → 0.5) so one odd frame can't drag a profile.
     */
    _touch(profile, observed) {
        profile.sightingCount += 1;
        profile.lastSeenAt = this.now();
        const weight = Math.min(0.5, 0.2 + profile.sightingCount * 0.05);
        for (let i = 0; i < profile.descriptor.length; i += 1) {
            profile.descriptor[i] = profile.descriptor[i] * (1 - weight) + observed[i] * weight;
        }
        this._persist();
        return profile;
    }

    // ── enrolment / editing ──────────────────────────────────────────────────

    /**
     * Add a person to the registry. The only path that creates a profile.
     * @param {number[]|Float32Array} descriptor
     * @param {{name?:string, notes?:string, id?:string}} meta
     */
    enroll(descriptor, meta = {}) {
        const vector = toDescriptor(descriptor);
        if (!vector) throw new Error('enroll: expected a 128-dimensional descriptor');
        const now = this.now();
        const profile = {
            id: meta.id || this._newId(),
            name: meta.name?.trim() || 'Unknown person',
            notes: meta.notes?.trim() || '',
            descriptor: vector,
            createdAt: now,
            lastSeenAt: now,
            sightingCount: 1,
            enrolled: true,
        };
        const existing = this.profiles.findIndex((p) => p.id === profile.id);
        if (existing >= 0) this.profiles[existing] = profile;
        else this.profiles.push(profile);
        this._persist();
        this._emit({ type: 'enrolled', profile: { ...profile, descriptor: undefined } });
        return { ...profile, descriptor: [...profile.descriptor] };
    }

    rename(id, name) {
        const profile = this.profiles.find((p) => p.id === id);
        if (!profile) return null;
        profile.name = name?.trim() || profile.name;
        this._persist();
        this._emit({ type: 'renamed', profile: { ...profile, descriptor: undefined } });
        return { ...profile, descriptor: undefined };
    }

    addNote(id, note) {
        const profile = this.profiles.find((p) => p.id === id);
        if (!profile || !note?.trim()) return null;
        profile.notes = profile.notes ? `${profile.notes}\n${note.trim()}` : note.trim();
        this._persist();
        this._emit({ type: 'noted', profile: { ...profile, descriptor: undefined } });
        return { ...profile, descriptor: undefined };
    }

    /** Forget a person entirely (the privacy-respecting delete). */
    forget(id) {
        const before = this.profiles.length;
        this.profiles = this.profiles.filter((p) => p.id !== id);
        const removed = this.profiles.length !== before;
        if (removed) {
            this._persist();
            this._emit({ type: 'forgotten', id });
        }
        return removed;
    }

    clear() {
        this.profiles = [];
        this._persist();
        this._emit({ type: 'cleared' });
    }

    // ── background search (ToDo §4: "do a background search") ───────────────

    /**
     * Run a background search for a newly-arrived person.
     *
     * Never blocks the UI and never rejects: identity detection is a
     * best-effort enrichment, so a failing search resolves to null and the
     * caller carries on. Concurrent calls for the same person share one
     * in-flight promise, so a face held in frame for ten seconds does not
     * launch ten searches.
     *
     * @param {object} profile
     * @param {(profile:object) => Promise<any>} search
     * @param {{timeoutMs?:number}} [options]
     */
    searchInBackground(profile, search, options = {}) {
        if (!profile?.id || typeof search !== 'function') return Promise.resolve(null);
        const existing = this.searches.get(profile.id);
        if (existing) return existing;

        const timeoutMs = options.timeoutMs ?? 8000;
        const task = (async () => {
            const timer = new Promise((resolve) => setTimeout(() => resolve(null), timeoutMs));
            try {
                const result = await Promise.race([Promise.resolve(search(profile)), timer]);
                this._emit({ type: 'searched', profileId: profile.id, result });
                return result ?? null;
            } catch (err) {
                console.warn('[personIdentity] background search failed:', err);
                return null;
            } finally {
                this.searches.delete(profile.id);
            }
        })();

        this.searches.set(profile.id, task);
        return task;
    }
}

/**
 * Describe an unidentified face so it can be shown in the panel while the user
 * decides who it is. Kept in memory only — an unnamed stranger has no business
 * being persisted.
 */
export function createPendingPerson(descriptor, now = Date.now()) {
    return {
        id: `pending-${now.toString(36)}`,
        name: '',
        enrolled: false,
        sightingCount: 1,
        lastSeenAt: now,
        descriptor: toDescriptor(descriptor),
    };
}

export default IdentityRegistry;