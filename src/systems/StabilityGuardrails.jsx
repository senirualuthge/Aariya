import { useEffect, useRef } from 'react';
import useStore from '../store';
import { tripleLoopRuntime } from '../core/tripleLoopRuntime';
import { EmotionGuardrail } from './emotionGuardrails';

/**
 * StabilityGuardrails
 * Implements "Invariant Checks" as suggested in analysis_recorrection_system.md.
 * Prevents "Dead Mannequin" or "Exploding Emotion" bugs by enforcing safe bounds,
 * and damps emotion oscillation (feedback-loop protection).
 *
 * The clamp + oscillation logic lives in `emotionGuardrails.js` so it is shared
 * with the live emotion heartbeat (DialogueSystem) and unit-tested on its own.
 */
export default function StabilityGuardrails() {
    const guardrailRef = useRef(null);
    if (guardrailRef.current === null) guardrailRef.current = new EmotionGuardrail();

    useEffect(() => {
        const guardrail = guardrailRef.current;

        const checkGuardrails = () => {
            const state = useStore.getState();
            const { emotions, socialIntent } = state;

            const updates = {};

            // 1 + 3. Emotion invariants: clamp to [0,1], rescue NaN, and damp
            //        oscillation back toward baseline.
            const guarded = guardrail.process(emotions || {});
            if (guarded.changed) updates.emotions = guarded.emotions;

            // 2. Social Intent Invariants
            if (socialIntent) {
                const si = { ...socialIntent };
                let siChanged = false;
                ['engagement', 'warmth', 'openness'].forEach(key => {
                    const val = si[key];
                    if (val < 0 || val > 1 || isNaN(val)) {
                        si[key] = Math.max(0, Math.min(1, isNaN(val) ? 0.5 : val));
                        siChanged = true;
                    }
                });
                if (si.dominance < -1 || si.dominance > 1 || isNaN(si.dominance)) {
                    si.dominance = Math.max(-1, Math.min(1, isNaN(si.dominance) ? 0 : si.dominance));
                    siChanged = true;
                }
                if (siChanged) updates.socialIntent = si;
            }

            if (Object.keys(updates).length > 0) {
                useStore.setState(updates);
            }
        };

        // Cognition-loop subscriber — priority 10 runs first (invariants before
        // behaviour/animation consumers read the emotion vector).
        const unsubscribe = tripleLoopRuntime.subscribeCognition(checkGuardrails, 10, 'StabilityGuardrails');

        return () => unsubscribe();
    }, []);

    return null;
}
