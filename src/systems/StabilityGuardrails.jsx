import { useEffect } from 'react';
import useStore from '../store';
import { runtime } from './RuntimeLoop';

/**
 * StabilityGuardrails
 * Implements "Invariant Checks" as suggested in analysis_recorrection_system.md.
 * Prevents "Dead Mannequin" or "Exploding Emotion" bugs by enforcing safe bounds.
 */
export default function StabilityGuardrails() {
    useEffect(() => {
        const checkGuardrails = (_dt) => {
            const state = useStore.getState();
            const { emotions, socialIntent } = state;
            
            let needsUpdate = false;
            const updates = {};

            // 1. Emotion Invariants (Clamp 0-1, handle NaN)
            const clampedEmotions = { ...emotions };
            Object.keys(emotions).forEach(key => {
                const val = emotions[key];
                if (isNaN(val) || val === undefined) {
                    clampedEmotions[key] = key === 'calm' ? 1.0 : 0.0;
                    needsUpdate = true;
                } else if (val < 0 || val > 1) {
                    clampedEmotions[key] = Math.max(0, Math.min(1, val));
                    needsUpdate = true;
                }
            });
            if (needsUpdate) updates.emotions = clampedEmotions;

            // 2. Social Intent Invariants
            if (socialIntent) {
                const si = { ...socialIntent };
                ['engagement', 'warmth', 'openness'].forEach(key => {
                    const val = si[key];
                    if (val < 0 || val > 1 || isNaN(val)) {
                        si[key] = Math.max(0, Math.min(1, isNaN(val) ? 0.5 : val));
                        needsUpdate = true;
                    }
                });
                if (si.dominance < -1 || si.dominance > 1 || isNaN(si.dominance)) {
                    si.dominance = Math.max(-1, Math.min(1, isNaN(si.dominance) ? 0 : si.dominance));
                    needsUpdate = true;
                }
                if (needsUpdate) updates.socialIntent = si;
            }

            // 3. Feedback Loop Protection
            // TODO: Detect oscillating emotions if needed

            if (needsUpdate) {
                useStore.setState(updates);
            }
        };

        // Priority 10 (First check in the loop)
        const unsubscribe = runtime.subscribe(checkGuardrails, 10, 'StabilityGuardrails');

        return () => unsubscribe();
    }, []);

    return null;
}
