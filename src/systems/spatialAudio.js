/**
 * src/systems/spatialAudio.js
 *
 * Real WebAudio spatial-output helpers for Meeting Mode (B4).
 *
 * The backend labels every reply with the diarized speaker it is addressed to
 * (`target_speaker_id` + a stable, id-ordered `target_speaker_slot` +
 * `speaker_count`). This module turns that slot into a stereo pan and provides
 * the sanctioned playback paths that apply it.
 *
 * Honest scope — read this before adding a caller:
 *   • This stack has NO microphone array, so there is no direction of arrival;
 *     a "slot" is a stable seating position, not a measured bearing.
 *   • There is NO server-side TTS. The live voice is `window.speechSynthesis`,
 *     whose output cannot be routed through the WebAudio graph — so it can
 *     never be panned. A pan is therefore applied only when REAL audio is played
 *     through this module (an AudioBuffer/URL, or an HTMLMediaElement). Nothing
 *     is faked for speech synthesis.
 *
 * `panForSlot` is the single source of truth for the slot → pan mapping; the UI
 * renders the same value it feeds the graph.
 */

/** Even left→right spread of `count` speaker slots across [-1, +1]. */
export function panForSlot(slot, count) {
    const n = Number.isFinite(count) ? Math.floor(count) : 0;
    if (n <= 1) return 0;
    if (!Number.isFinite(slot)) return 0;
    const i = Math.max(0, Math.min(n - 1, Math.floor(slot)));
    return -1 + (2 * i) / (n - 1);
}

const clampPan = (p) => Math.max(-1, Math.min(1, Number.isFinite(p) ? p : 0));

let _ctx = null;

/** Lazily create (and cache) the output AudioContext; null outside a browser. */
export function getSpatialContext() {
    if (typeof window === 'undefined') return null;
    const Ctor = window.AudioContext || window.webkitAudioContext;
    if (!Ctor) return null;
    if (!_ctx) _ctx = new Ctor();
    return _ctx;
}

/**
 * Play a real audio source through a StereoPannerNode.
 * @param {AudioBuffer|string} source  decoded buffer, or a URL to fetch+decode
 * @param {number} pan                 -1 (left) … +1 (right)
 * @returns {Promise<boolean>} true when audio actually played
 */
export async function playPannedAudio(source, pan = 0, { volume = 1 } = {}) {
    const ctx = getSpatialContext();
    if (!ctx || !source) return false;
    if (ctx.state === 'suspended') {
        try { await ctx.resume(); } catch { /* autoplay gate — caller retries on gesture */ }
    }

    let buffer = source;
    if (typeof source === 'string') {
        try {
            const res = await fetch(source);
            buffer = await ctx.decodeAudioData(await res.arrayBuffer());
        } catch {
            return false;
        }
    }
    if (!buffer) return false;

    const src = ctx.createBufferSource();
    src.buffer = buffer;
    const gain = ctx.createGain();
    gain.gain.value = Number.isFinite(volume) ? volume : 1;

    if (typeof ctx.createStereoPanner === 'function') {
        const panner = ctx.createStereoPanner();
        panner.pan.value = clampPan(pan);
        src.connect(gain).connect(panner).connect(ctx.destination);
    } else {
        // No StereoPannerNode (very old Safari): play centred rather than fake it.
        src.connect(gain).connect(ctx.destination);
    }
    src.start();
    return true;
}

// One MediaElementSource per element (creating a second throws).
const _elementNodes = new WeakMap();

/**
 * Route a real <audio>/<video> element through a panner. Idempotent per element.
 * @returns {StereoPannerNode|null}
 */
export function attachPanner(mediaElement, pan = 0) {
    const ctx = getSpatialContext();
    if (!ctx || !mediaElement || typeof ctx.createStereoPanner !== 'function') return null;

    let entry = _elementNodes.get(mediaElement);
    if (!entry) {
        const src = ctx.createMediaElementSource(mediaElement);
        const panner = ctx.createStereoPanner();
        src.connect(panner).connect(ctx.destination);
        entry = { src, panner };
        _elementNodes.set(mediaElement, entry);
    }
    entry.panner.pan.value = clampPan(pan);
    return entry.panner;
}

/** Reset the cached context (tests / hot reload). */
export function _resetSpatialAudioForTests() {
    _ctx = null;
}
