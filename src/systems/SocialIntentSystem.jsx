import { useEffect } from 'react';
import useStore from '../store';
import { tripleLoopRuntime } from '../core/tripleLoopRuntime';
import { neuralEngine } from './ai/NeuralEngine';

/**
 * SocialIntentSystem
 *
 * Derives Aariya's conversational stance (LISTENING / COMFORTING / TEASING /
 * SETTING_BOUNDARY + warmth/dominance/openness/engagement) from the live emotion
 * vector, on the cognition loop. Runs as a pure rule pass — no synthetic data.
 */
const SocialIntentSystem = () => {
    const setSocialIntent = useStore((state) => state.setSocialIntent);

    useEffect(() => {
        const updateSocialIntent = (dt) => {
            const state = useStore.getState();
            const newIntent = neuralEngine.resolveSocialIntent(state, dt);
            setSocialIntent(newIntent);
        };

        // Priority 30 — after the emotion update, before behaviour/animation.
        const unsubscribe = tripleLoopRuntime.subscribeCognition(
            updateSocialIntent, 30, 'SocialIntentSystem',
        );

        return () => unsubscribe();
    }, [setSocialIntent]);

    return null;
};

export default SocialIntentSystem;
