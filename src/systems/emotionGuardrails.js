/**
 * src/systems/emotionGuardrails.js
 *
 * Pure, dependency-free invariant checks for Aariya's emotion vector —
 * "Stability Guardrails" (analysis_recorrection_system.md):
 *
 *   1. Bounds/invalid clamp — keeps every axis inside [0, 1] and rescues
 *      NaN/undefined so a single bad frame can't poison the animation layer.
 *   2. Feedback-loop protection — detects *oscillation* (an axis repeatedly
 *      flipping above/below its baseline inside a short window) and damps it
 *      toward the baseline, breaking accidental feedback loops between the
 *      emotion, personality and animation layers.
 *
 * Everything is derived from the real emotion series it is fed; the baseline is
 * a code constant that mirrors the store's default emotions.
 */

/** Baseline emotion vector — mirrors `store.js` initial `emotions`. */
export const EMOTION_BASELINE = Object.freeze({
    happy: 0.5,
    calm: 0.5,
    excited: 0.0,
    sad: 0.0,
    angry: 0.0,
    focused: 0.3,
});

const clamp01 = (v) => Math.max(0, Math.min(1, v));

/**
 * Clamp an emotion vector to [0, 1] and replace non-finite values with the
 * baseline for that axis (falling back to 0 for unknown axes).
 *
 * @returns {{ emotions: Object, changed: boolean }}
 */
export function clampEmotions(emotions, baseline = EMOTION_BASELINE) {
    const out = {};
    let changed = false;

    for (const key of Object.keys(emotions || {})) {
        const val = emotions[key];
        const base = typeof baseline[key] === 'number' ? baseline[key] : 0;
        if (typeof val !== 'number' || !Number.isFinite(val)) {
            out[key] = base;
            changed = true;
        } else if (val < 0 || val > 1) {
            out[key] = clamp01(val);
            changed = true;
        } else {
            out[key] = val;
        }
    }

    return { emotions: out, changed };
}

/**
 * Count direction changes in a series: how many times it reverses (up→down or
 * down→up). A flat or steadily-rising series scores 0; a value ping-ponging
 * up/down scores high.
 */
export function countSignFlips(series) {
    if (!series || series.length < 3) return 0;
    let flips = 0;
    let prevDir = 0;
    for (let i = 1; i < series.length; i++) {
        const d = series[i] - series[i - 1];
        const dir = d > 1e-9 ? 1 : d < -1e-9 ? -1 : 0;
        if (dir !== 0) {
            if (prevDir !== 0 && dir !== prevDir) flips++;
            prevDir = dir;
        }
    }
    return flips;
}

/**
 * Stateful guardrail: keeps a short rolling history per axis, flags
 * oscillation, and damps the offending axes back toward baseline.
 */
export class EmotionGuardrail {
    /**
     * @param {Object} [opts]
     * @param {number} [opts.windowMs]      history window considered for oscillation
     * @param {number} [opts.flipThreshold] sign flips within the window that count as oscillation
     * @param {number} [opts.damping]       fraction [0,1] to pull an oscillating axis toward baseline
     * @param {Object} [opts.baseline]      baseline vector
     */
    constructor(opts = {}) {
        this.windowMs = opts.windowMs ?? 4000;
        this.flipThreshold = opts.flipThreshold ?? 4;
        this.damping = opts.damping ?? 0.5;
        this.baseline = opts.baseline ?? EMOTION_BASELINE;
        this.history = []; // [{ t, values: {axis: number} }]
    }

    reset() {
        this.history = [];
    }

    /**
     * Clamp, record, detect, and (if needed) damp.
     *
     * @param {Object} emotions  the freshly-computed emotion vector
     * @param {number} [now]     timestamp (ms); injectable for tests
     * @returns {{ emotions: Object, changed: boolean, oscillationDetected: boolean, flips: Object }}
     */
    process(emotions, now = Date.now()) {
        const { emotions: clamped, changed: clampedChanged } = clampEmotions(emotions, this.baseline);

        this.history.push({ t: now, values: clamped });
        const cutoff = now - this.windowMs;
        this.history = this.history.filter((s) => s.t >= cutoff);

        const flips = {};
        let oscillationDetected = false;

        for (const key of Object.keys(clamped)) {
            const series = this.history
                .map((s) => s.values[key])
                .filter((v) => typeof v === 'number');
            const n = countSignFlips(series);
            flips[key] = n;
            if (n >= this.flipThreshold) oscillationDetected = true;
        }

        let out = clamped;
        let changed = clampedChanged;

        if (oscillationDetected) {
            out = {};
            for (const key of Object.keys(clamped)) {
                const base = typeof this.baseline[key] === 'number' ? this.baseline[key] : 0;
                const damped = clamped[key] + (base - clamped[key]) * this.damping;
                if (Math.abs(damped - clamped[key]) > 1e-9) changed = true;
                out[key] = clamp01(damped);
            }
        }

        return { emotions: out, changed, oscillationDetected, flips };
    }
}
