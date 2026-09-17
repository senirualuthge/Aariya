/**
 * src/systems/ai/NeuralEngine.js
 * Adaptive Behavior Core — deterministic social-intent rules.
 *
 * Previously this trained a TF.js network on 200 Math.random() samples to
 * "clone" the hand-written heuristics below, then ran inference over them.
 * The synthetic training data violated the project's no-synthetic-data rule
 * and added a model indirection with zero information gain. The rules are
 * now applied directly: same observable behavior, fully deterministic.
 */

export class NeuralEngine {
    constructor() {
        this.enabled = true;
        this.lastUpdate = Date.now();
        this.updateRate = 200; // 200ms tick
    }

    /**
     * Main tick. Kept for DialogueSystem API compatibility.
     * @returns null (no per-tick side effects)
     */
    update(inputs) {
        if (!this.enabled) return null;

        const now = Date.now();
        if (now - this.lastUpdate < this.updateRate) return null;
        this.lastUpdate = now;

        return null;
    }

    /**
     * Resolve Social Intent from the current emotional state using explicit
     * rules (the same policy the old network was trained to imitate).
     *
     * @param {Object} state - { emotions, socialIntent }
     * @param {number} dt - delta time in seconds
     * @returns {Object} updated social intent
     */
    resolveSocialIntent(state, dt) {
        const { emotions, socialIntent } = state;
        const currentIntent = { ...socialIntent };

        const sad = emotions.sad || 0;
        const angry = emotions.angry || 0;
        const happy = emotions.happy || 0;
        const arousal = emotions.arousal || 0;

        // Rule selection (priority: sad > angry > playful > listen)
        let intent = 'LISTENING';
        let wDelta = 0, dDelta = 0, oDelta = 0;
        if (sad > 0.6) {
            intent = 'COMFORTING'; wDelta = 0.5;
        } else if (angry > 0.5) {
            intent = 'SETTING_BOUNDARY'; dDelta = 0.3;
        } else if (happy > 0.6 && arousal > 0.5) {
            intent = 'TEASING'; oDelta = 0.2;
        }
        currentIntent.intent = intent;

        // Apply personality deltas scaled by dt
        currentIntent.warmth = this.clamp(currentIntent.warmth + wDelta * dt, 0, 1);
        currentIntent.dominance = this.clamp(currentIntent.dominance + dDelta * dt, 0, 1);
        currentIntent.openness = this.clamp(currentIntent.openness + oDelta * dt, 0, 1);

        // Engagement decays unless refreshed by interaction elsewhere
        currentIntent.engagement = Math.max(0, (currentIntent.engagement || 0.5) - dt * 0.01);

        return currentIntent;
    }

    /**
     * Personality evolution from weekly session stats (heuristic).
     * @param {Object} current - { warmth, energy, assertiveness, formality }
     * @param {Object} stats - { avg_valence, avg_arousal, valence_volatility }
     * @returns {Object} new personality
     */
    calculatePersonalityEvolution(current, stats) {
        if (!stats || !current) return current;
        const { avg_valence, avg_arousal, valence_volatility } = stats;
        const warmth_target = this.clamp(0.6 * avg_valence + 0.4 * (1 - valence_volatility), -1, 1);
        const energy_target = this.clamp(avg_arousal, 0, 1);
        const assertiveness_target = this.clamp(1 - valence_volatility, 0, 1);
        const formality_target = current.formality;
        const alpha = 0.01;
        return {
            warmth: this.clamp((1 - alpha) * current.warmth + alpha * warmth_target, -0.4, 0.6),
            energy: this.clamp((1 - alpha) * current.energy + alpha * energy_target, 0.2, 0.8),
            assertiveness: this.clamp((1 - alpha) * current.assertiveness + alpha * assertiveness_target, 0.2, 0.7),
            formality: this.clamp((1 - alpha) * current.formality + alpha * formality_target, 0.3, 0.8)
        };
    }

    clamp(val, min, max) {
        return Math.max(min, Math.min(max, val));
    }
}

export const neuralEngine = new NeuralEngine();
