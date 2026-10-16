/**
 * src/systems/audioEmotion.js
 *
 * Pure helpers that turn the REAL microphone spectrum into a user-affect
 * estimate, and fuse it with a facial signal when one exists.
 *
 * Nothing here fabricates data: every value is a function of the live analyser
 * buffers. The reference constants below are documented code constants (a
 * resting-speech calibration), the same category as the label↔valence mapping
 * used by the emotion guardrails.
 *
 * Low-signal honesty: near-silence yields `confidence ≈ 0`, so the fusion step
 * drops the reading instead of claiming the user is "sad".
 */

/** Resting-speech calibration references (heuristic, pending real calibration). */
export const AUDIO_REFS = {
    /** Spectral centroid (0..1 of Nyquist) typical of calm speech. */
    pitchMid: 0.25,
    /** Mean spectrum level (0..1) typical of calm speech. */
    energyMid: 0.12,
    /** Additional level that reads as "full voice". */
    energySpan: 0.3,
};

/** Rolling frame count used for the tempo/variation estimate. */
export const FEATURE_WINDOW = 30;

/** How often the derived affect is pushed to the store (ms). */
export const AFFECT_PUBLISH_MS = 200;

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const clamp11 = (v) => clamp(v, -1, 1);
const clamp01 = (v) => clamp(v, 0, 1);
/** Coerce a possibly-missing/non-finite number to 0 so NaN never leaks out. */
const num = (v) => (Number.isFinite(v) ? v : 0);

/**
 * Extract frame features from a byte frequency spectrum (0..255 per bin).
 * @param {ArrayLike<number>} freqData
 * @returns {{energy: number, pitch: number}} energy and spectral centroid, both 0..1
 */
export function extractAudioFeatures(freqData) {
    const n = freqData ? freqData.length : 0;
    if (!n) return { energy: 0, pitch: 0 };

    let sum = 0;
    let weighted = 0;
    for (let i = 0; i < n; i++) {
        const v = freqData[i];
        sum += v;
        weighted += i * v;
    }

    const energy = sum / n / 255;
    // Spectral centroid = brightness → a real pitch proxy (not an F0 estimate).
    const pitch = sum > 0 ? weighted / sum / n : 0;
    return { energy, pitch };
}

/**
 * Variation of a per-frame energy history — the "tempo" term (0..1).
 * @param {number[]} history most recent last
 */
export function variationFromHistory(history) {
    if (!Array.isArray(history) || history.length < 2) return 0;
    let delta = 0;
    for (let i = 1; i < history.length; i++) {
        delta += Math.abs(history[i] - history[i - 1]);
    }
    const mean = delta / (history.length - 1);
    // 0.25 mean frame-to-frame delta reads as full-scale variation.
    return clamp01(mean / 0.25);
}

/**
 * Map audio features to a user-affect estimate.
 * @returns {{valence: number, arousal: number, confidence: number}}
 */
export function audioToEmotion({ energy = 0, pitch = 0, tempo = 0 } = {}) {
    const ref = AUDIO_REFS;
    const level = num(energy);
    const brightness = num(pitch);
    const variation = num(tempo);

    // Brightness relative to resting speech → valence (symmetric: rest ≈ 0).
    const pitchDelta = clamp11((brightness - ref.pitchMid) / ref.pitchMid);
    // Level above resting speech → arousal; near-silence → no confidence.
    const energyNorm = clamp01((level - ref.energyMid) / ref.energySpan);
    const confidence = clamp01(level / ref.energySpan);

    return {
        valence: clamp11(pitchDelta * 0.8 + energyNorm * 0.2),
        arousal: clamp01(energyNorm * 0.7 + clamp01(variation) * 0.3),
        confidence,
    };
}

/**
 * Dominant mood label for a valence/arousal pair. Labels match the palette
 * used by the presence overlay so the reading renders with the right colour.
 */
export function dominantAffect(valence, arousal) {
    const v = clamp11(valence);
    const a = clamp01(arousal);

    if (a >= 0.65) return v <= -0.25 ? 'stressed' : 'excited';
    if (a >= 0.35) {
        if (v <= -0.25) return 'angry';
        return v >= 0.15 ? 'happy' : 'neutral';
    }
    if (v >= 0.15) return 'calm';
    if (v <= -0.25) return 'tired';
    return 'neutral';
}

/**
 * Fuse the facial and audio affect estimates into the store's `userEmotion`.
 *
 * Only signals that actually carry information take part: a source with
 * `confidence <= 0` is ignored, and with no usable source this returns `null`
 * so the caller can leave the previous reading untouched.
 *
 * @param {{face?: object|null, audio?: object|null}} sources
 * @returns {{primary: string, valence: number, arousal: number, confidence: number, source: string}|null}
 */
export function fuseUserAffect({ face = null, audio = null } = {}) {
    const parts = [];
    if (face && (face.confidence ?? 1) > 0) parts.push({ ...face, source: 'face' });
    if (audio && (audio.confidence ?? 0) > 0) parts.push({ ...audio, source: 'audio' });

    if (parts.length === 0) return null;
    if (parts.length === 1) {
        const only = parts[0];
        return {
            primary: only.primary || dominantAffect(only.valence || 0, only.arousal || 0),
            valence: clamp11(num(only.valence)),
            arousal: clamp01(num(only.arousal)),
            confidence: clamp01(num(only.confidence ?? 1)),
            source: only.source,
        };
    }

    let weight = 0;
    let valence = 0;
    let arousal = 0;
    for (const p of parts) {
        // Raw confidence is the blend weight (not clamped — a firmer signal
        // should dominate); it is only clamped for the reported value.
        const raw = num(p.confidence);
        const w = raw > 0 ? raw : 1;
        weight += w;
        valence += num(p.valence) * w;
        arousal += num(p.arousal) * w;
    }
    valence /= weight;
    arousal /= weight;

    return {
        primary: dominantAffect(valence, arousal),
        valence: clamp11(valence),
        arousal: clamp01(arousal),
        confidence: clamp01(weight / parts.length),
        source: parts.map((p) => p.source).join('+'),
    };
}
