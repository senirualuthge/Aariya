// src/utils/privacySwitches.js
//
// System-wide microphone / camera kill switches (ToDo §5).
//
// Both switches are enforced in ONE place instead of at each of the five
// getUserMedia call sites (OrbAvatar, useCamera, useAudioAnalyzer,
// AudioEmotionSystem, gevRealtime). A single interceptor around
// navigator.mediaDevices.getUserMedia:
//
//   1. refuses a request whose device is switched off, so no new capture can
//      start anywhere in the app — including the GEV realtime voice path that
//      has its own capture logic;
//   2. remembers every stream it hands out, so flipping a switch off can stop
//      tracks that are ALREADY live (stopping the switch is not enough on its
//      own — an already-running getUserMedia stream keeps recording).
//
// The authoritative state lives on the server (kill_switches.py /
// /api/sdk/killswitches), so a switch set in one surface applies everywhere and
// survives a reload. Until that state is fetched we optimistically allow
// capture: a failed fetch must not silently disable the user's microphone.
// A local override set in this session always wins over a later fetch, so the
// UI doesn't fight the user when a stale server response lands.

import { apiBase } from './apiHost.js';

const KINDS = ['microphone', 'camera'];

/** Server-confirmed state plus any local override applied this session. */
const state = {
    microphone: { allowed: true, override: null },
    camera: { allowed: true, override: null },
};

const listeners = new Set();
const streams = { microphone: new Set(), camera: new Set() };
let interceptorInstalled = false;

export class CaptureBlockedError extends Error {
    constructor(kind) {
        super(`Capture blocked: the ${kind} is switched off system-wide.`);
        this.name = 'CaptureBlockedError';
        this.kind = kind;
    }
}

export function isCaptureAllowed(kind) {
    const entry = state[kind];
    if (!entry) return true;
    if (entry.override !== null) return entry.override;
    return entry.allowed;
}

/** Subscribe to state changes (returns an unsubscribe function). */
export function onCaptureChange(callback) {
    listeners.add(callback);
    return () => listeners.delete(callback);
}

function currentState() {
    return Object.fromEntries(KINDS.map((kind) => [kind, isCaptureAllowed(kind)]));
}

function emit() {
    const snapshot = currentState();
    for (const cb of listeners) {
        try {
            cb(snapshot);
        } catch (err) {
            console.warn('[privacy] capture-state listener failed:', err);
        }
    }
}

/** Stop every live track of one kind. Safe to call when nothing is running. */
export function stopCapture(kind) {
    const live = streams[kind];
    if (!live || live.size === 0) return 0;
    for (const stream of live) {
        for (const track of stream.getTracks()) {
            if (kind === 'microphone' ? track.kind === 'audio' : track.kind === 'video') {
                track.stop();
            }
        }
    }
    live.clear();
    return live.size;
}

/** Apply a state, stopping live tracks for anything that just became blocked. */
function apply(kind, allowed) {
    const entry = state[kind];
    const changed = entry.allowed !== allowed;
    entry.allowed = allowed;
    if (changed && !allowed) stopCapture(kind);
    if (changed) emit();
    return changed;
}

function kindsFromConstraints(constraints) {
    if (!constraints) return [];
    const kinds = [];
    // A falsy `video: false` is an explicit "no video" — same for audio.
    if (constraints.audio) kinds.push('microphone');
    if (constraints.video) kinds.push('camera');
    return kinds;
}

function installInterceptor() {
    if (interceptorInstalled) return;
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) return;

    interceptorInstalled = true;
    const media = navigator.mediaDevices;
    const original = media.getUserMedia.bind(media);

    media.getUserMedia = async (constraints) => {
        const wanted = kindsFromConstraints(constraints);
        const blocked = wanted.find((kind) => !isCaptureAllowed(kind));
        if (blocked) throw new CaptureBlockedError(blocked);

        const stream = await original(constraints);
        for (const kind of wanted) {
            streams[kind].add(stream);
            const forget = () => streams[kind].delete(stream);
            for (const track of stream.getTracks()) track.addEventListener('ended', forget);
        }
        return stream;
    };
}

/**
 * Pull authoritative state from the server. Never throws: a failed request
 * leaves the current (optimistic) state alone.
 */
export async function loadCaptureState() {
    installInterceptor();
    try {
        const res = await fetch(`${apiBase()}/api/sdk/killswitches/state`);
        if (!res.ok) return currentState();
        const data = await res.json();
        const flags = data?.flags;
        if (!flags) return currentState();
        for (const kind of KINDS) {
            if (typeof flags[kind] === 'boolean') apply(kind, flags[kind]);
        }
    } catch {
        // Server unreachable (offline / booting) — keep optimistic state.
    }
    return currentState();
}

/**
 * Toggle one switch system-wide: persist on the server, then enforce locally
 * so the effect is immediate. The local override wins over later server polls.
 */
export async function setCaptureEnabled(kind, enabled) {
    installInterceptor();
    state[kind].override = Boolean(enabled);
    apply(kind, Boolean(enabled));
    try {
        await fetch(`${apiBase()}/api/sdk/killswitches/toggle`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ flag: kind, enabled: Boolean(enabled), reason: 'ui privacy switch' }),
        });
    } catch {
        // Local enforcement already applied; the server copy catches up on the
        // next loadCaptureState().
    }
    return isCaptureAllowed(kind);
}

/**
 * Call once at app start. Loads server state, refreshes when the window
 * regains focus (so a switch flipped on the mobile app reaches the desktop
 * app), and installs the interceptor.
 */
export function initPrivacySwitches() {
    installInterceptor();
    loadCaptureState();
    if (typeof window !== 'undefined' && !window.__privacySwitchesBound) {
        window.__privacySwitchesBound = true;
        window.addEventListener('focus', () => loadCaptureState());
    }
    return currentState();
}